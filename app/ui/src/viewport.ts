import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { FaceAxis, FaceRange, FaceFeatureProfile, MeshData, EdgeRef } from "./types";
import { mapMeshPositionsForViewport } from "./meshBinary";
import { edgePoints } from "./sceneSelection";
import { resizeAnchor, resizeChanged, resizeDirection, resizedDimensions, sizeLabel } from "./bodyResizing";
import type { BodyResize, ResizeHandle, Size3 } from "./bodyResizing";
import { constrainedSize, snapTranslation } from "./designer";
import type {
  FaceDomePreview, FaceEditTarget, FaceFeaturePreview, SheetBendPreview,
} from "./faceEditing";

export type ViewName = "top" | "front" | "side" | "iso";
export type TransformAxis = "x" | "y" | "z";

export interface PartTransformTarget {
  partId: string;
  solidIndices: number[];
  bbox?: number[];
}

export interface DesignerPointerTool {
  kind: "sketch" | "sculpt" | "edge";
  origin?: Size3;
  normal?: Size3;
  radius?: number;
  start: (point: Size3) => void;
  move: (point: Size3, delta: Size3) => void;
  finish: (cancelled: boolean) => void;
  numeric?: (value: number) => void;
}

export interface ViewportEvents {
  onHoverFace: (face: number | null) => void;
  onSelectFace: (face: number | null, additive?: boolean) => void;
  onSelectEdge: (edge: EdgeRef) => void;
  onPushPullStart: () => void;
  onPushPullPreview: (delta: number) => void;
  onPushPullCommit: (delta: number) => void;
  onPartMovePreview: (axis: TransformAxis, delta: number) => void;
  onPartMoveCommit: (axis: TransformAxis, delta: number) => void;
  onBodyResizePreview: (size: Size3 | null) => void;
  onBodyResizeCommit: (resize: BodyResize) => void;
  onCameraRotated: () => void;
  onCameraZoomed: () => void;
}

const COLOR = {
  ground: 0xefedea,
  gridMinor: 0xdcd9d4,
  gridMajor: 0xc9c5bf,
  body: 0xdcd9d4,
  bodyEdge: 0xb8b3ac,
  selFace: 0xd97706,
  selBody: 0xb45309,
  selEdge: 0x1d4ed8,
  hover: 0xa8a29e,
  axisX: 0x9c4a3d,
  axisY: 0x4a7a52,
  axisZ: 0x3d5a8a,
  dim: 0x8a3f06,
};

function docToThree(x: number, y: number, z: number): [number, number, number] {
  return [x, z, -y];
}

function pointSegmentDistance(point: THREE.Vector2, start: THREE.Vector2, end: THREE.Vector2): number {
  const segment = end.clone().sub(start);
  const lengthSquared = segment.lengthSq();
  if (lengthSquared <= 1e-9) return point.distanceTo(start);
  const amount = Math.max(0, Math.min(1, point.clone().sub(start).dot(segment) / lengthSquared));
  return point.distanceTo(start.clone().add(segment.multiplyScalar(amount)));
}

function axisVector(axis: FaceAxis): [number, number, number] {
  if (axis === "x") return [1, 0, 0];
  if (axis === "y") return [0, 1, 0];
  return [0, 0, 1];
}

function faceFeatureShape(profile: FaceFeatureProfile): THREE.Shape {
  const shape = new THREE.Shape();
  if (profile.kind === "rectangle") {
    const halfWidth = (profile.width ?? 0) / 2;
    const halfHeight = (profile.height ?? 0) / 2;
    shape.moveTo(-halfWidth, -halfHeight);
    shape.lineTo(halfWidth, -halfHeight);
    shape.lineTo(halfWidth, halfHeight);
    shape.lineTo(-halfWidth, halfHeight);
    shape.closePath();
    return shape;
  }
  if (profile.kind === "slot") {
    const radius = (profile.width ?? 0) / 2;
    const halfStraight = ((profile.length ?? 0) - (profile.width ?? 0)) / 2;
    shape.moveTo(-halfStraight, -radius);
    shape.lineTo(halfStraight, -radius);
    shape.absarc(halfStraight, 0, radius, -Math.PI / 2, Math.PI / 2, false);
    shape.lineTo(-halfStraight, radius);
    shape.absarc(-halfStraight, 0, radius, Math.PI / 2, Math.PI * 1.5, false);
    shape.closePath();
    return shape;
  }
  const outerRadius = profile.kind === "ring"
    ? (profile.outer_diameter ?? 0) / 2
    : (profile.diameter ?? 0) / 2;
  shape.absarc(0, 0, outerRadius, 0, Math.PI * 2, false);
  if (profile.kind === "ring") {
    const hole = new THREE.Path();
    hole.absarc(0, 0, (profile.inner_diameter ?? 0) / 2, 0, Math.PI * 2, true);
    shape.holes.push(hole);
  }
  return shape;
}

function faceDomeGeometry(diameter: number, height: number): THREE.BufferGeometry {
  const segments = 48;
  const rings = 16;
  const baseRadius = diameter / 2;
  const sphereRadius = (baseRadius * baseRadius + height * height) / (2 * height);
  const sphereCenter = height - sphereRadius;
  const positions: number[] = [];
  const indices: number[] = [];

  for (let ring = 0; ring < rings; ring += 1) {
    const z = height * ring / rings;
    const radius = Math.sqrt(Math.max(0, sphereRadius * sphereRadius - (z - sphereCenter) ** 2));
    for (let segment = 0; segment < segments; segment += 1) {
      const angle = segment * Math.PI * 2 / segments;
      positions.push(radius * Math.cos(angle), radius * Math.sin(angle), z);
    }
  }
  const apex = positions.length / 3;
  positions.push(0, 0, height);
  const baseCenter = positions.length / 3;
  positions.push(0, 0, 0);

  for (let ring = 0; ring < rings - 1; ring += 1) {
    for (let segment = 0; segment < segments; segment += 1) {
      const next = (segment + 1) % segments;
      const currentRing = ring * segments;
      const nextRing = (ring + 1) * segments;
      indices.push(
        currentRing + segment, currentRing + next, nextRing + segment,
        currentRing + next, nextRing + next, nextRing + segment,
      );
    }
  }
  const lastRing = (rings - 1) * segments;
  for (let segment = 0; segment < segments; segment += 1) {
    const next = (segment + 1) % segments;
    indices.push(lastRing + segment, lastRing + next, apex);
    indices.push(baseCenter, next, segment);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function brakeFormGeometry(
  args: SheetBendPreview["args"],
  bends: SheetBendPreview["bends"],
  developedLength: number,
  stationWidth: number,
  thickness: number,
  transformPoint: (x: number, y: number, z: number) => [number, number, number],
): THREE.BufferGeometry {
  const specs = bends.map((bend) => {
    const angle = THREE.MathUtils.degToRad(bend.angle);
    const delta = bend.direction * angle;
    const allowance = (bend.inside_radius + thickness / 2) * angle;
    const center = bend.position + developedLength / 2;
    return {
      ...bend,
      delta,
      pathRadius: bend.direction > 0 ? bend.inside_radius : bend.inside_radius + thickness,
      zoneStart: center - allowance / 2,
      zoneEnd: center + allowance / 2,
    };
  }).sort((left, right) => left.position - right.position);

  const advance = (
    point: [number, number],
    tangentAngle: number,
    delta: number,
    radius: number,
  ): [number, number] => {
    const absoluteDelta = Math.abs(delta);
    const localX = radius * Math.sin(absoluteDelta);
    const localZ = Math.sign(delta) * radius * (1 - Math.cos(absoluteDelta));
    const cosine = Math.cos(tangentAngle);
    const sine = Math.sin(tangentAngle);
    return [
      point[0] + localX * cosine - localZ * sine,
      point[1] + localX * sine + localZ * cosine,
    ];
  };

  type SectionPiece = {
    kind: "straight" | "bend";
    start: number;
    end: number;
    point: [number, number];
    angle: number;
    delta: number;
    radius: number;
  };
  const pieces: SectionPiece[] = [];
  let tangentAngle = -specs
    .filter((spec) => spec.moving_side < 0)
    .reduce((total, spec) => total + spec.delta, 0);
  let point: [number, number] = [0, 0];
  let cursor = 0;
  for (const spec of specs) {
    const straightLength = spec.zoneStart - cursor;
    pieces.push({
      kind: "straight", start: cursor, end: spec.zoneStart,
      point, angle: tangentAngle, delta: 0, radius: 0,
    });
    point = [
      point[0] + straightLength * Math.cos(tangentAngle),
      point[1] + straightLength * Math.sin(tangentAngle),
    ];
    pieces.push({
      kind: "bend", start: spec.zoneStart, end: spec.zoneEnd,
      point, angle: tangentAngle, delta: spec.delta, radius: spec.pathRadius,
    });
    point = advance(point, tangentAngle, spec.delta, spec.pathRadius);
    tangentAngle += spec.delta;
    cursor = spec.zoneEnd;
  }
  pieces.push({
    kind: "straight", start: cursor, end: developedLength,
    point, angle: tangentAngle, delta: 0, radius: 0,
  });

  const pointAt = (developed: number): [number, number, number] => {
    const piece = pieces.find((candidate) =>
      developed >= candidate.start - 1e-9 && developed <= candidate.end + 1e-9) ?? pieces[pieces.length - 1];
    if (piece.kind === "straight") {
      const distance = developed - piece.start;
      return [
        piece.point[0] + distance * Math.cos(piece.angle),
        piece.point[1] + distance * Math.sin(piece.angle),
        piece.angle,
      ];
    }
    const fraction = (developed - piece.start) / (piece.end - piece.start);
    const localDelta = piece.delta * Math.max(0, Math.min(1, fraction));
    const bendPoint = advance(piece.point, piece.angle, localDelta, piece.radius);
    return [bendPoint[0], bendPoint[1], piece.angle + localDelta];
  };

  const negativeSpecs = specs.filter((spec) => spec.moving_side < 0);
  const positiveSpecs = specs.filter((spec) => spec.moving_side > 0);
  const anchorDeveloped = negativeSpecs.length === 0
    ? 0
    : positiveSpecs.length === 0
      ? developedLength
      : (negativeSpecs[negativeSpecs.length - 1].zoneEnd + positiveSpecs[0].zoneStart) / 2;
  const anchor = pointAt(anchorDeveloped);
  const shiftX = -developedLength / 2 + anchorDeveloped - anchor[0];
  const shiftZ = -anchor[1];
  const stationPositions = [0];
  const bendSegments = 24;
  for (const spec of specs) {
    stationPositions.push(spec.zoneStart);
    for (let index = 1; index < bendSegments; index += 1) {
      stationPositions.push(spec.zoneStart + (spec.zoneEnd - spec.zoneStart) * index / bendSegments);
    }
    stationPositions.push(spec.zoneEnd);
  }
  stationPositions.push(developedLength);

  const section = (developed: number) => {
    const [rawX, rawZ, localAngle] = pointAt(developed);
    const innerX = rawX + shiftX;
    const innerZ = thickness + rawZ + shiftZ;
    const outerX = innerX + thickness * Math.sin(localAngle);
    const outerZ = innerZ - thickness * Math.cos(localAngle);
    return [
      transformPoint(innerX, -stationWidth / 2, innerZ),
      transformPoint(innerX, stationWidth / 2, innerZ),
      transformPoint(outerX, -stationWidth / 2, outerZ),
      transformPoint(outerX, stationWidth / 2, outerZ),
    ];
  };

  const positions: number[] = [];
  const indices: number[] = [];
  for (const developed of stationPositions) {
    for (const point of section(developed)) positions.push(...docToThree(...point));
  }
  for (let station = 0; station < stationPositions.length - 1; station += 1) {
    const current = station * 4;
    const next = current + 4;
    indices.push(
      current, next, current + 1, current + 1, next, next + 1,
      current + 2, current + 3, next + 2, current + 3, next + 3, next + 2,
      current, current + 2, next, current + 2, next + 2, next,
      current + 1, next + 1, current + 3, current + 3, next + 1, next + 3,
    );
  }
  const last = (stationPositions.length - 1) * 4;
  indices.push(0, 1, 2, 1, 3, 2, last, last + 2, last + 1, last + 1, last + 2, last + 3);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function sheetBendGeometry(preview: SheetBendPreview): THREE.BufferGeometry {
  const { args, bends, length, width, thickness, target } = preview;
  if (target.axis === "z" || target.axis == null) {
    const developedLength = args.bend_axis === "x" ? length : width;
    const stationWidth = args.bend_axis === "x" ? width : length;
    return brakeFormGeometry(
      args,
      bends,
      developedLength,
      stationWidth,
      thickness,
      (x, y, z) => args.bend_axis === "y" ? [-y, x, z] : [x, y, z],
    );
  }

  const base = bends[0];
  const baseDevelopedLength = base.bend_axis === "x" ? length : width;
  const flangeWidth = base.bend_axis === "x" ? width : length;
  const baseAngle = THREE.MathUtils.degToRad(base.angle);
  const baseDelta = base.direction * baseAngle;
  const baseAllowance = (base.inside_radius + thickness / 2) * baseAngle;
  const baseCenter = base.position + baseDevelopedLength / 2;
  const zoneStart = baseCenter - baseAllowance / 2;
  const zoneEnd = baseCenter + baseAllowance / 2;
  const pathRadius = base.direction > 0
    ? base.inside_radius
    : base.inside_radius + thickness;
  const initialAngle = base.moving_side < 0 ? -baseDelta : 0;
  const lineEnd: [number, number] = [
    zoneStart * Math.cos(initialAngle),
    zoneStart * Math.sin(initialAngle),
  ];
  const advance = (
    point: [number, number],
    tangentAngle: number,
    delta: number,
    radius: number,
  ): [number, number] => {
    const absoluteDelta = Math.abs(delta);
    const localX = radius * Math.sin(absoluteDelta);
    const localZ = Math.sign(delta) * radius * (1 - Math.cos(absoluteDelta));
    const cosine = Math.cos(tangentAngle);
    const sine = Math.sin(tangentAngle);
    return [
      point[0] + localX * cosine - localZ * sine,
      point[1] + localX * sine + localZ * cosine,
    ];
  };
  const arcEnd = advance(lineEnd, initialAngle, baseDelta, pathRadius);
  const finalAngle = initialAngle + baseDelta;
  const finalPoint: [number, number] = [
    arcEnd[0] + (baseDevelopedLength - zoneEnd) * Math.cos(finalAngle),
    arcEnd[1] + (baseDevelopedLength - zoneEnd) * Math.sin(finalAngle),
  ];
  const negativeFlange = base.moving_side < 0;
  const anchorDeveloped = negativeFlange ? baseDevelopedLength : 0;
  const anchorPoint: [number, number] = negativeFlange ? finalPoint : [0, 0];
  const rootPoint = negativeFlange ? lineEnd : arcEnd;
  const rootTangent2d: [number, number] = negativeFlange
    ? [-Math.cos(initialAngle), -Math.sin(initialAngle)]
    : [Math.cos(finalAngle), Math.sin(finalAngle)];
  const flangeDepth = negativeFlange ? zoneStart : baseDevelopedLength - zoneEnd;
  const shiftX = -baseDevelopedLength / 2 + anchorDeveloped - anchorPoint[0];
  const shiftZ = -anchorPoint[1];
  const rootCross = rootPoint[0] + shiftX;
  const rootZ = thickness + rootPoint[1] + shiftZ;
  const root: [number, number, number] = base.bend_axis === "x"
    ? [rootCross, 0, rootZ]
    : [0, rootCross, rootZ];
  const tangent: [number, number, number] = base.bend_axis === "x"
    ? [rootTangent2d[0], 0, rootTangent2d[1]]
    : [0, rootTangent2d[0], rootTangent2d[1]];
  const selectedNormal: [number, number, number] = target.axis === "x"
    ? [target.side, 0, 0]
    : [0, target.side, 0];
  const thicknessAxis: [number, number, number] = [
    base.direction * selectedNormal[0],
    base.direction * selectedNormal[1],
    base.direction * selectedNormal[2],
  ];
  const localXAxis: [number, number, number] = [
    tangent[1] * thicknessAxis[2] - tangent[2] * thicknessAxis[1],
    tangent[2] * thicknessAxis[0] - tangent[0] * thicknessAxis[2],
    tangent[0] * thicknessAxis[1] - tangent[1] * thicknessAxis[0],
  ];
  const perpendicularAxis: [number, number, number] = base.bend_axis === "x"
    ? [0, 1, 0]
    : [1, 0, 0];
  const localAxisSign = Math.round(
    localXAxis[0] * perpendicularAxis[0] +
    localXAxis[1] * perpendicularAxis[1] +
    localXAxis[2] * perpendicularAxis[2],
  ) as -1 | 1;
  const localArgs: SheetBendPreview["args"] = {
    ...args,
    face_ref: { ...args.face_ref, axis: "z", side: 1 },
    bend_axis: "x",
    position: localAxisSign * args.position,
    moving_side: (localAxisSign * args.moving_side) as -1 | 1,
    direction: (base.direction * args.direction) as -1 | 1,
  };
  const planeOrigin: [number, number, number] = [
    root[0] + flangeDepth / 2 * tangent[0],
    root[1] + flangeDepth / 2 * tangent[1],
    root[2] + flangeDepth / 2 * tangent[2],
  ];
  return brakeFormGeometry(
    localArgs,
    [localArgs],
    flangeWidth,
    flangeDepth,
    thickness,
    (x, y, z) => [
      planeOrigin[0] + x * localXAxis[0] + y * tangent[0] + z * thicknessAxis[0],
      planeOrigin[1] + x * localXAxis[1] + y * tangent[1] + z * thicknessAxis[1],
      planeOrigin[2] + x * localXAxis[2] + y * tangent[2] + z * thicknessAxis[2],
    ],
  );
}

function makeTextSprite(text: string): THREE.Sprite {
  const pad = 12;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  const font = "500 28px Onest, system-ui, sans-serif";
  ctx.font = font;
  const w = Math.ceil(ctx.measureText(text).width) + pad * 2;
  const h = 44;
  canvas.width = w * 2; canvas.height = h * 2;
  ctx.scale(2, 2);
  ctx.font = font;
  ctx.fillStyle = "#8a3f06";
  ctx.textBaseline = "middle";
  ctx.fillText(text, pad, h / 2);
  const tex = new THREE.CanvasTexture(canvas);
  tex.anisotropy = 4;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
  const sprite = new THREE.Sprite(mat);
  const scale = 0.28;
  sprite.scale.set((w / h) * scale * 10, scale * 10, 1);
  sprite.renderOrder = 20;
  return sprite;
}

function disposeObject(object: THREE.Object3D) {
  object.traverse((child) => {
    const renderable = child as THREE.Object3D & {
      geometry?: THREE.BufferGeometry;
      material?: THREE.Material | THREE.Material[];
    };
    renderable.geometry?.dispose();
    const materials = Array.isArray(renderable.material) ? renderable.material : [renderable.material];
    for (const material of materials) {
      if (!material) continue;
      const mapped = material as THREE.Material & { map?: THREE.Texture | null };
      mapped.map?.dispose();
      material.dispose();
    }
  });
}

function subGeometry(geo: THREE.BufferGeometry, range: FaceRange): THREE.BufferGeometry {
  return subGeometryRanges(geo, [range]);
}

function subGeometryRanges(geo: THREE.BufferGeometry, ranges: FaceRange[]): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  const sourcePositions = geo.getAttribute("position");
  const source = geo.getIndex()!;
  const positions = new Float32Array(ranges.reduce((count, range) => count + range.tri_count, 0) * 9);
  let destination = 0;
  for (const range of ranges) {
    for (let offset = range.tri_start * 3; offset < (range.tri_start + range.tri_count) * 3; offset += 1) {
      const index = source.getX(offset);
      positions[destination++] = sourcePositions.getX(index);
      positions[destination++] = sourcePositions.getY(index);
      positions[destination++] = sourcePositions.getZ(index);
    }
  }
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  return geometry;
}

function rangesBounds(geo: THREE.BufferGeometry, ranges: FaceRange[]): THREE.Box3 | null {
  const source = geo.getIndex();
  const position = geo.getAttribute("position") as THREE.BufferAttribute;
  if (!source || ranges.length === 0) return null;
  const bounds = new THREE.Box3();
  const point = new THREE.Vector3();
  let found = false;
  for (const range of ranges) {
    for (let offset = range.tri_start * 3; offset < (range.tri_start + range.tri_count) * 3; offset += 1) {
      point.fromBufferAttribute(position, Number(source.getX(offset)));
      bounds.expandByPoint(point);
      found = true;
    }
  }
  return found ? bounds : null;
}

export class Viewport {
  private container: HTMLElement;
  private events: ViewportEvents;
  private renderer!: THREE.WebGLRenderer;
  private scene!: THREE.Scene;
  private persp!: THREE.PerspectiveCamera;
  private ortho!: THREE.OrthographicCamera;
  private camera!: THREE.Camera;
  private controls!: OrbitControls;
  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2();
  private mesh: THREE.Mesh | null = null;
  private faceRanges: FaceRange[] = [];
  private hiddenSolids = new Set<number>();
  private selectionHint: ((label: string) => void) | null = null;
  private selectionCycle: { x: number; y: number; faces: number[]; index: number } | null = null;
  private printDiagnosticGroup: THREE.Group | null = null;
  private hoverOverlay: THREE.Object3D | null = null;
  private selOverlay: THREE.Object3D | null = null;
  private edgeMarker: THREE.Group | null = null;
  private hoverEdge: THREE.Line | null = null;
  private splitPreview: THREE.Mesh | null = null;
  private editingEnabled = true;
  private edgeSelectionActive = false;
  private selectableEdges: EdgeRef[] = [];
  private pushPullGroup: THREE.Group | null = null;
  private pushPullTarget: FaceEditTarget | null = null;
  private pushPullLabel: THREE.Sprite | null = null;
  private selectedSolidsOverlay: THREE.Mesh | null = null;
  private transformGroup: THREE.Group | null = null;
  private transformTarget: (PartTransformTarget & { center: THREE.Vector3 }) | null = null;
  private transformLabel: THREE.Sprite | null = null;
  private bodyResizeGroup: THREE.Group | null = null;
  private bodyResizeLabel: THREE.Sprite | null = null;
  private bodyResizeTarget: (PartTransformTarget & { minimum: Size3; maximum: Size3; size: Size3 }) | null = null;
  private bodyResizeOriginal: THREE.BufferGeometry | null = null;
  private bodyResizePreview: THREE.BufferGeometry | null = null;
  private bodyResizeVertices = new Set<number>();
  private bodyResizeDrag: {
    pointerId: number; startX: number; startY: number;
    direction: THREE.Vector2; pixelsPerMm: number;
    handle: ResizeHandle; size: Size3;
  } | null = null;
  private faceFeatureGroup: THREE.Group | null = null;
  private faceDomeGroup: THREE.Group | null = null;
  private sheetBendGroup: THREE.Group | null = null;
  private pushPullDrag: {
    pointerId: number;
    startX: number;
    startY: number;
    screenDirection: THREE.Vector2;
    pixelsPerMm: number;
    delta: number;
  } | null = null;
  private transformDrag: {
    pointerId: number;
    startX: number;
    startY: number;
    screenDirection: THREE.Vector2;
    pixelsPerMm: number;
    axis: TransformAxis;
    delta: number;
  } | null = null;
  private dimGroup: THREE.Group | null = null;
  private operationPreview: THREE.Mesh | null = null;
  private designerTool: DesignerPointerTool | null = null;
  private designerDrag: { pointerId: number; start: THREE.Vector3; startX: number; plane: THREE.Plane } | null = null;
  private designerMarker: THREE.Object3D | null = null;
  private designerContext: ((x: number, y: number) => void) | null = null;
  private dimensionEdit: ((axis: number) => void) | null = null;
  private dimensionBounds: number[] | null = null;
  private dimensionData: MeshData | null = null;
  private numericDrag = "";
  private designerPull: ((delta: number, commit: boolean) => void) | null = null;
  private resizeConstraint = "free";
  private snapSettings: { bounds: number[]; others: number[][]; grid: number } | null = null;
  private snapGuide: THREE.PlaneHelper | null = null;
  private resizeObs!: ResizeObserver;
  private downPos = { x: 0, y: 0 };
  private orthoMode = false;
  private halfSize = 100;
  private navigationProbe: {
    durationMs: number;
    startedAt: number | null;
    frames: number;
    position: THREE.Vector3;
    quaternion: THREE.Quaternion;
    resolve: (result: { fps: number; frames: number; duration_ms: number }) => void;
  } | null = null;

  constructor(container: HTMLElement, events: ViewportEvents) {
    this.container = container;
    this.events = events;
    this.init();
  }

  private init() {
    const w = this.container.clientWidth || 800;
    const h = this.container.clientHeight || 600;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(w, h);
    this.container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(COLOR.ground);

    this.persp = new THREE.PerspectiveCamera(45, w / h, 0.1, 5000);
    this.persp.position.set(140, 120, 140);
    this.ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, -2000, 4000);
    this.ortho.position.copy(this.persp.position);
    this.updateOrthoFrustum();
    this.camera = this.persp;

    const hemi = new THREE.HemisphereLight(0xffffff, 0xc9c5bf, 0.95);
    const dir = new THREE.DirectionalLight(0xffffff, 0.9);
    dir.position.set(80, 140, 60);
    this.scene.add(hemi, dir);

    this.buildGrid();

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.configureControls();
    const wheelHandler = () => this.events.onCameraZoomed();
    this.renderer.domElement.addEventListener("wheel", wheelHandler, { passive: true });

    this.renderer.domElement.addEventListener("pointermove", (e) => this.onPointerMove(e));
    this.renderer.domElement.addEventListener("pointerdown", (e) => this.onPointerDown(e), true);
    this.renderer.domElement.addEventListener("pointerup", (e) => this.onPointerUp(e), true);
    this.renderer.domElement.addEventListener("pointercancel", (e) => this.onPointerCancel(e), true);
    this.renderer.domElement.addEventListener("lostpointercapture", (e) => this.onPointerCancel(e), true);
    this.renderer.domElement.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      if (!this.editingEnabled || this.designerDrag) return;
      this.onClick(e as PointerEvent);
      this.designerContext?.(e.clientX, e.clientY);
    });
    this.renderer.domElement.addEventListener("dblclick", (event) => {
      if (!this.editingEnabled) return;
      const axis = this.pickDimension(event as PointerEvent);
      if (axis != null) this.dimensionEdit?.(axis);
    });

    this.resizeObs = new ResizeObserver(() => this.onResize());
    this.resizeObs.observe(this.container);
    this.animate();
  }

  private configureControls() {
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN,
    };
    this.controls.addEventListener("change", () => this.render());
    let initialRotation: THREE.Quaternion | null = null;
    this.controls.addEventListener("start", () => { initialRotation = this.camera.quaternion.clone(); });
    this.controls.addEventListener("end", () => {
      if (initialRotation && initialRotation.angleTo(this.camera.quaternion) > 1e-5) {
        this.events.onCameraRotated();
      }
      initialRotation = null;
    });
  }

  private buildGrid() {
    const extent = 500;
    const minor: number[] = [];
    const major: number[] = [];
    for (let i = -extent; i <= extent; i += 10) {
      const target = i % 50 === 0 ? major : minor;
      target.push(i, 0, -extent, i, 0, extent);
      target.push(-extent, 0, i, extent, 0, i);
    }
    const mk = (verts: number[], color: number) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
      return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color }));
    };
    this.scene.add(mk(minor, COLOR.gridMinor), mk(major, COLOR.gridMajor));

    const axes = new THREE.Group();
    const axis = (dir: [number, number, number], color: number) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, ...dir], 3));
      axes.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color })));
    };
    axis([extent, 0, 0], COLOR.axisX);   // doc X
    axis([0, 0, -extent], COLOR.axisY);  // doc Y
    axis([0, extent, 0], COLOR.axisZ);   // doc Z
    this.scene.add(axes);
  }

  private onResize() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.persp.aspect = w / h;
    this.persp.updateProjectionMatrix();
    this.updateOrthoFrustum();
    this.render();
  }

  private updateOrthoFrustum() {
    const w = this.container.clientWidth || 800;
    const h = this.container.clientHeight || 600;
    const aspect = w / h;
    this.ortho.left = -this.halfSize * aspect;
    this.ortho.right = this.halfSize * aspect;
    this.ortho.top = this.halfSize;
    this.ortho.bottom = -this.halfSize;
    this.ortho.updateProjectionMatrix();
  }

  private animate = (timestamp = performance.now()) => {
    requestAnimationFrame(this.animate);
    const probe = this.navigationProbe;
    if (probe) {
      if (probe.startedAt === null) probe.startedAt = timestamp;
      probe.frames += 1;
      const offset = this.camera.position.clone().sub(this.controls.target);
      offset.applyAxisAngle(new THREE.Vector3(0, 1, 0), 0.012);
      this.camera.position.copy(this.controls.target).add(offset);
      this.camera.lookAt(this.controls.target);
      const elapsed = timestamp - probe.startedAt;
      if (elapsed >= probe.durationMs) {
        this.camera.position.copy(probe.position);
        this.camera.quaternion.copy(probe.quaternion);
        this.controls.update();
        this.navigationProbe = null;
        probe.resolve({
          fps: elapsed > 0 ? Math.max(0, probe.frames - 1) * 1000 / elapsed : 0,
          frames: probe.frames,
          duration_ms: elapsed,
        });
      }
    }
    if (this.controls.enableDamping) this.controls.update();
    this.render();
  };

  measureNavigationFps(durationMs: number): Promise<{ fps: number; frames: number; duration_ms: number }> {
    if (this.navigationProbe) {
      return Promise.reject(new Error("Измерение viewport FPS уже выполняется"));
    }
    return new Promise((resolve) => {
      this.navigationProbe = {
        durationMs: Math.max(500, durationMs),
        startedAt: null,
        frames: 0,
        position: this.camera.position.clone(),
        quaternion: this.camera.quaternion.clone(),
        resolve,
      };
    });
  }

  private render() {
    this.updateBodyResizeHandleSizes();
    this.renderer.render(this.scene, this.camera);
  }

  private pickFace(e: PointerEvent): number | null {
    if (!this.mesh) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObject(this.mesh, false);
    const faces: number[] = [];
    for (const hit of hits) {
      const triangle = hit.faceIndex;
      if (triangle == null) continue;
      const range = this.faceRanges.find((candidate) => triangle >= candidate.tri_start && triangle < candidate.tri_start + candidate.tri_count);
      if (!range || this.hiddenSolids.has(range.solid_index ?? -1) || faces.includes(range.face_index)) continue;
      faces.push(range.face_index);
    }
    if (!e.altKey) return faces[0] ?? null;
    const previous = this.selectionCycle;
    const same = previous && Math.hypot(previous.x - e.clientX, previous.y - e.clientY) < 5 && previous.faces.join() === faces.join();
    const index = same && faces.length ? (previous.index + 1) % faces.length : 0;
    this.selectionCycle = { x: e.clientX, y: e.clientY, faces, index };
    return faces[index] ?? null;
  }

  private updatePointer(e: PointerEvent) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
  }

  private pickPushPullHandle(e: PointerEvent): boolean {
    if (!this.pushPullGroup) return false;
    this.updatePointer(e);
    return this.raycaster.intersectObject(this.pushPullGroup, true)
      .some((hit) => hit.object.userData.pushPullHandle === true);
  }

  private pickTransformAxis(e: PointerEvent): TransformAxis | null {
    if (!this.transformGroup) return null;
    this.updatePointer(e);
    const hit = this.raycaster.intersectObject(this.transformGroup, true)
      .find((candidate) => candidate.object.userData.transformAxis != null);
    return (hit?.object.userData.transformAxis as TransformAxis | undefined) ?? null;
  }

  private pickEdge(e: PointerEvent): EdgeRef | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(e.clientX - rect.left, e.clientY - rect.top);
    let best: { edge: EdgeRef; distance: number; depth: number } | null = null;
    for (const edge of this.selectableEdges) {
      if (this.hiddenSolids.has(edge.solid_index)) continue;
      const points = edgePoints(edge);
      for (let index = 1; index < points.length; index += 1) {
      const worldStart = new THREE.Vector3(...docToThree(...points[index - 1]));
      const worldEnd = new THREE.Vector3(...docToThree(...points[index]));
      const startProjected = worldStart.clone().project(this.camera);
      const endProjected = worldEnd.clone().project(this.camera);
      if (startProjected.z < -1 || startProjected.z > 1 || endProjected.z < -1 || endProjected.z > 1) continue;
      const start = new THREE.Vector2(
        (startProjected.x + 1) * rect.width / 2,
        (1 - startProjected.y) * rect.height / 2,
      );
      const end = new THREE.Vector2(
        (endProjected.x + 1) * rect.width / 2,
        (1 - endProjected.y) * rect.height / 2,
      );
      const distance = pointSegmentDistance(pointer, start, end);
      const depth = (startProjected.z + endProjected.z) / 2;
      if (distance > 8) continue;
      const segment = end.clone().sub(start);
      const amount = segment.lengthSq() > 1e-9
        ? THREE.MathUtils.clamp(pointer.clone().sub(start).dot(segment) / segment.lengthSq(), 0, 1)
        : 0;
      const point = worldStart.clone().lerp(worldEnd, amount);
      const projected = point.clone().project(this.camera);
      this.raycaster.setFromCamera(new THREE.Vector2(projected.x, projected.y), this.camera);
      const surface = this.mesh ? this.raycaster.intersectObject(this.mesh, false)[0] : null;
      if (surface && point.distanceTo(surface.point) > Math.max(0.05, this.halfSize * 0.002)) continue;
      if (!best || distance < best.distance - 1 ||
          (Math.abs(distance - best.distance) <= 1 && depth < best.depth)) {
        best = { edge, distance, depth };
      }
      }
    }
    return best?.edge ?? null;
  }

  private pushPullScreenScale(target: FaceEditTarget): {
    direction: THREE.Vector2;
    pixelsPerMm: number;
  } {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const [cx, cy, cz] = docToThree(...target.center);
    const [nx, ny, nz] = docToThree(...target.normal);
    const origin = new THREE.Vector3(cx, cy, cz).project(this.camera);
    const sample = new THREE.Vector3(cx + nx * 10, cy + ny * 10, cz + nz * 10).project(this.camera);
    const screen = new THREE.Vector2(
      (sample.x - origin.x) * rect.width / 2,
      -(sample.y - origin.y) * rect.height / 2,
    );
    const pixelsPerMm = screen.length() / 10;
    if (pixelsPerMm < 0.15) return { direction: new THREE.Vector2(0, -1), pixelsPerMm: 2 };
    return { direction: screen.normalize(), pixelsPerMm };
  }

  private transformScreenScale(axis: TransformAxis): {
    direction: THREE.Vector2;
    pixelsPerMm: number;
  } {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const center = this.transformTarget?.center ?? new THREE.Vector3();
    const [dx, dy, dz] = docToThree(...axisVector(axis));
    const origin = center.clone().project(this.camera);
    const sample = center.clone().add(new THREE.Vector3(dx, dy, dz).multiplyScalar(10)).project(this.camera);
    const screen = new THREE.Vector2(
      (sample.x - origin.x) * rect.width / 2,
      -(sample.y - origin.y) * rect.height / 2,
    );
    const pixelsPerMm = screen.length() / 10;
    if (pixelsPerMm < 0.15) return { direction: new THREE.Vector2(0, -1), pixelsPerMm: 2 };
    return { direction: screen.normalize(), pixelsPerMm };
  }

  private onPointerDown(e: PointerEvent) {
    if (this.bodyResizeDrag || this.transformDrag || this.pushPullDrag || this.designerDrag) return;
    this.downPos = { x: e.clientX, y: e.clientY };
    if (e.button !== 0 || !this.editingEnabled) return;
    this.numericDrag = "";
    if (this.designerTool) {
      const tool = this.designerTool;
      this.updatePointer(e);
      let start: THREE.Vector3 | null = null;
      const normal = tool.normal ? new THREE.Vector3(...docToThree(...tool.normal)) : this.camera.getWorldDirection(new THREE.Vector3());
      if (tool.kind === "sculpt") start = this.mesh ? this.raycaster.intersectObject(this.mesh, false)[0]?.point ?? null : null;
      else if (tool.origin) {
        const origin = new THREE.Vector3(...docToThree(...tool.origin));
        if (tool.kind === "edge") {
          const rect = this.renderer.domElement.getBoundingClientRect();
          const screen = origin.clone().project(this.camera);
          if (Math.hypot(e.clientX - rect.left - (screen.x + 1) * rect.width / 2,
            e.clientY - rect.top - (1 - screen.y) * rect.height / 2) > 24) return;
        }
        start = this.raycaster.ray.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(normal, origin), new THREE.Vector3());
      }
      if (!start) return;
      e.preventDefault(); e.stopPropagation();
      this.designerDrag = { pointerId: e.pointerId, start, startX: e.clientX, plane: new THREE.Plane().setFromNormalAndCoplanarPoint(normal, start) };
      if (this.designerMarker && tool.kind === "sculpt") { this.designerMarker.position.copy(start); this.designerMarker.visible = true; }
      this.controls.enabled = false;
      this.renderer.domElement.setPointerCapture(e.pointerId);
      tool.start([start.x, -start.z, start.y]);
      return;
    }
    const resizeHandle = this.pickBodyResizeHandle(e);
    if (resizeHandle && this.bodyResizeTarget) {
      e.preventDefault();
      e.stopPropagation();
      const target = this.bodyResizeTarget;
      const center = target.size.map((_, axis) => resizeHandle.axis == null || axis === resizeHandle.axis
        ? resizeHandle.corner[axis] < 0 ? target.minimum[axis] : target.maximum[axis]
        : (target.minimum[axis] + target.maximum[axis]) / 2) as Size3;
      const origin = new THREE.Vector3(...docToThree(...center));
      const direction = new THREE.Vector3(...docToThree(...resizeDirection(target.size, resizeHandle)));
      const rect = this.renderer.domElement.getBoundingClientRect();
      const projected = origin.clone().project(this.camera);
      const sample = origin.clone().addScaledVector(direction, 10).project(this.camera);
      const screen = new THREE.Vector2((sample.x - projected.x) * rect.width / 2, -(sample.y - projected.y) * rect.height / 2);
      const pixelsPerMm = screen.length() / 10;
      this.bodyResizeDrag = {
        pointerId: e.pointerId, startX: e.clientX, startY: e.clientY,
        direction: pixelsPerMm >= 0.15 ? screen.normalize() : new THREE.Vector2(0, -1),
        pixelsPerMm: pixelsPerMm >= 0.15 ? pixelsPerMm : 2,
        handle: resizeHandle, size: [...target.size],
      };
      this.controls.enabled = false;
      this.renderer.domElement.setPointerCapture(e.pointerId);
      this.renderer.domElement.style.cursor = "grabbing";
      return;
    }
    const transformAxis = this.pickTransformAxis(e);
    if (transformAxis && this.transformTarget) {
      e.preventDefault();
      e.stopPropagation();
      const scale = this.transformScreenScale(transformAxis);
      this.transformDrag = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        screenDirection: scale.direction,
        pixelsPerMm: scale.pixelsPerMm,
        axis: transformAxis,
        delta: 0,
      };
      this.controls.enabled = false;
      this.renderer.domElement.setPointerCapture(e.pointerId);
      this.renderer.domElement.style.cursor = "grabbing";
      return;
    }
    if (!this.pushPullTarget || !this.pickPushPullHandle(e)) return;
    e.preventDefault();
    e.stopPropagation();
    const scale = this.pushPullScreenScale(this.pushPullTarget);
    this.pushPullDrag = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      screenDirection: scale.direction,
      pixelsPerMm: scale.pixelsPerMm,
      delta: 0,
    };
    this.controls.enabled = false;
    this.renderer.domElement.setPointerCapture(e.pointerId);
    this.renderer.domElement.style.cursor = "grabbing";
    if (!this.designerPull) this.events.onPushPullStart();
  }

  private onPointerMove(e: PointerEvent) {
    if (this.numericDrag && (this.bodyResizeDrag || this.transformDrag || this.pushPullDrag || this.designerDrag)) return;
    if (this.designerDrag) {
      if (e.pointerId !== this.designerDrag.pointerId) return;
      e.preventDefault();
      this.updatePointer(e);
      const point = this.raycaster.ray.intersectPlane(this.designerDrag.plane, new THREE.Vector3());
      if (point) {
        const delta = point.clone().sub(this.designerDrag.start);
        this.designerTool?.move([point.x, -point.z, point.y], this.designerTool.kind === "edge"
          ? [(e.clientX - this.designerDrag.startX) / 4, 0, 0] : [delta.x, -delta.z, delta.y]);
      }
      return;
    }
    if (this.designerTool?.kind === "sculpt" && this.designerMarker && this.editingEnabled && this.mesh) {
      this.updatePointer(e);
      const hit = this.raycaster.intersectObject(this.mesh, false)[0];
      this.designerMarker.visible = !!hit;
      if (hit) this.designerMarker.position.copy(hit.point);
      this.render(); return;
    }
    if (this.bodyResizeDrag && e.pointerId !== this.bodyResizeDrag.pointerId) return;
    if (this.bodyResizeDrag && e.pointerId === this.bodyResizeDrag.pointerId && this.bodyResizeTarget) {
      e.preventDefault();
      const drag = this.bodyResizeDrag;
      const movement = new THREE.Vector2(e.clientX - drag.startX, e.clientY - drag.startY);
      const delta = movement.dot(drag.direction) / drag.pixelsPerMm;
      drag.size = resizedDimensions(this.bodyResizeTarget.size, drag.handle, delta, e.shiftKey);
      if (drag.handle.axis != null) drag.size = constrainedSize(this.bodyResizeTarget.size, drag.handle.axis, drag.size[drag.handle.axis], this.resizeConstraint);
      this.previewBodyResize(drag.handle, drag.size);
      this.events.onBodyResizePreview(drag.size);
      return;
    }
    if (this.transformDrag && e.pointerId === this.transformDrag.pointerId) {
      e.preventDefault();
      const movement = new THREE.Vector2(
        e.clientX - this.transformDrag.startX,
        e.clientY - this.transformDrag.startY,
      );
      const delta = movement.dot(this.transformDrag.screenDirection) / this.transformDrag.pixelsPerMm;
      const axis = "xyz".indexOf(this.transformDrag.axis);
      const snapped = this.snapSettings ? snapTranslation(this.snapSettings.bounds, this.snapSettings.others, axis, delta,
        e.shiftKey ? 0.1 : this.snapSettings.grid, e.altKey ? 0 : 1) : null;
      this.transformDrag.delta = snapped?.delta ?? Math.round(delta * 10) / 10;
      if (this.snapGuide) { this.scene.remove(this.snapGuide); disposeObject(this.snapGuide); this.snapGuide = null; }
      if (snapped?.target != null && this.snapSettings) {
        const normal = new THREE.Vector3(...docToThree(...axisVector(this.transformDrag.axis)));
        const size = Math.max(...this.snapSettings.bounds.slice(3).map((value, index) => value - this.snapSettings!.bounds[index])) * 2;
        this.snapGuide = new THREE.PlaneHelper(new THREE.Plane(normal, -snapped.target), size, 0x2b8858);
        this.scene.add(this.snapGuide);
      }
      this.setTransformPreview(this.transformDrag.axis, this.transformDrag.delta);
      if (snapped && this.transformLabel) {
        const previous = this.transformLabel;
        const label = makeTextSprite(`${this.transformDrag.delta.toFixed(2)} мм · ${snapped.label}`);
        label.position.copy(previous.position); previous.parent?.remove(previous); disposeObject(previous);
        this.transformLabel = label; this.transformGroup?.add(label);
      }
      this.events.onPartMovePreview(this.transformDrag.axis, this.transformDrag.delta);
      return;
    }
    if (this.pushPullDrag && e.pointerId === this.pushPullDrag.pointerId) {
      e.preventDefault();
      const movement = new THREE.Vector2(
        e.clientX - this.pushPullDrag.startX,
        e.clientY - this.pushPullDrag.startY,
      );
      const delta = movement.dot(this.pushPullDrag.screenDirection) / this.pushPullDrag.pixelsPerMm;
      this.pushPullDrag.delta = Math.round(delta * 10) / 10;
      if (this.designerPull) this.designerPull(this.pushPullDrag.delta, false);
      else { this.setPushPullPreview(this.pushPullDrag.delta); this.events.onPushPullPreview(this.pushPullDrag.delta); }
      return;
    }
    if (!this.editingEnabled) { this.renderer.domElement.style.cursor = "default"; return; }
    const overResize = this.pickBodyResizeHandle(e);
    if (overResize) {
      this.setHoverFace(null); this.setHoverEdge(null);
      this.renderer.domElement.style.cursor = "grab";
      return;
    }
    const overTransform = this.pickTransformAxis(e);
    const overHandle = this.pickPushPullHandle(e);
    const edge = !overTransform && !overHandle && !this.bodyResizeTarget && !this.transformTarget && !e.shiftKey ? this.pickEdge(e) : null;
    this.setHoverEdge(edge);
    this.renderer.domElement.style.cursor = overTransform || overHandle ? "grab" : edge ? "crosshair" : "default";
    const face = edge || this.edgeSelectionActive ? null : this.pickFace({ clientX: e.clientX, clientY: e.clientY, altKey: false } as PointerEvent);
    const range = this.faceRanges.find((candidate) => candidate.face_index === face);
    this.selectionHint?.(edge ? "Ребро · щелчок для скругления или фаски" : range ? `${range.surface_ref?.kind === "cylinder" ? "Цилиндрическая поверхность" : range.face_ref ? "Плоская грань" : "Поверхность"}${range.feature_index != null ? " · редактируемый элемент" : ""} · Alt+щелчок: следующий слой` : "Выберите тело, грань или ребро");
    this.setHoverFace(face);
    this.events.onHoverFace(face);
  }

  private onPointerUp(e: PointerEvent) {
    if (this.designerDrag) {
      if (e.pointerId === this.designerDrag.pointerId && e.button === 0) this.finishDesignerDrag(false);
      return;
    }
    if (this.bodyResizeDrag && e.pointerId !== this.bodyResizeDrag.pointerId) return;
    if (this.bodyResizeDrag && e.pointerId === this.bodyResizeDrag.pointerId && e.button === 0) {
      e.preventDefault(); e.stopPropagation();
      const drag = this.bodyResizeDrag;
      const target = this.bodyResizeTarget;
      this.bodyResizeDrag = null;
      this.controls.enabled = true;
      if (this.renderer.domElement.hasPointerCapture(e.pointerId)) this.renderer.domElement.releasePointerCapture(e.pointerId);
      this.renderer.domElement.style.cursor = "grab";
      if (target && resizeChanged(target.size, drag.size)) {
        this.events.onBodyResizeCommit({ target_id: target.partId, size: drag.size, anchor: resizeAnchor(drag.handle) });
      } else this.cancelBodyResizePreview();
      return;
    }
    if (this.transformDrag && e.pointerId === this.transformDrag.pointerId) {
      e.preventDefault();
      e.stopPropagation();
      const { axis, delta } = this.transformDrag;
      this.transformDrag = null;
      this.controls.enabled = true;
      this.renderer.domElement.releasePointerCapture(e.pointerId);
      this.renderer.domElement.style.cursor = "grab";
      if (Math.abs(delta) >= 0.05) this.events.onPartMoveCommit(axis, delta);
      else this.cancelTransformPreview();
      return;
    }
    if (this.pushPullDrag && e.pointerId === this.pushPullDrag.pointerId) {
      e.preventDefault();
      e.stopPropagation();
      const delta = this.pushPullDrag.delta;
      this.pushPullDrag = null;
      this.controls.enabled = true;
      this.renderer.domElement.releasePointerCapture(e.pointerId);
      this.renderer.domElement.style.cursor = "grab";
      if (Math.abs(delta) >= 0.05 && this.designerPull) this.designerPull(delta, true);
      else if (Math.abs(delta) >= 0.05) this.events.onPushPullCommit(delta);
      else this.cancelPushPullPreview();
      return;
    }
    if (e.button !== 0) return;
    const dx = e.clientX - this.downPos.x;
    const dy = e.clientY - this.downPos.y;
    if (dx * dx + dy * dy < 25) this.onClick(e);
  }

  private onPointerCancel(e: PointerEvent) {
    if (this.designerDrag?.pointerId === e.pointerId) { this.finishDesignerDrag(true); return; }
    if (this.bodyResizeDrag && e.pointerId === this.bodyResizeDrag.pointerId) {
      this.cancelBodyResizePreview();
      return;
    }
    if (this.transformDrag && e.pointerId === this.transformDrag.pointerId) {
      const axis = this.transformDrag.axis;
      this.controls.enabled = true;
      this.renderer.domElement.style.cursor = "default";
      this.cancelTransformPreview();
      this.events.onPartMovePreview(axis, 0);
      return;
    }
    if (!this.pushPullDrag || e.pointerId !== this.pushPullDrag.pointerId) return;
    this.controls.enabled = true;
    this.renderer.domElement.style.cursor = "default";
    this.cancelPushPullPreview();
    this.events.onPushPullPreview(0);
  }

  private onClick(e: PointerEvent) {
    if (!this.editingEnabled) return;
    if (this.pickDimension(e) != null) return;
    if (this.designerTool) return;
    const edge = !this.bodyResizeTarget && !this.transformTarget && !e.shiftKey && !e.altKey ? this.pickEdge(e) : null;
    if (edge) { this.events.onSelectEdge(edge); return; }
    if (this.edgeSelectionActive) return;
    const face = this.pickFace(e);
    this.events.onSelectFace(face, e.shiftKey);
  }

  private setHoverEdge(edge: EdgeRef | null) {
    if (this.hoverEdge) {
      this.scene.remove(this.hoverEdge);
      disposeObject(this.hoverEdge);
      this.hoverEdge = null;
    }
    if (!edge) return;
    const points = edgePoints(edge).map((point) => new THREE.Vector3(...docToThree(...point)));
    if (points.length < 2) return;
    this.hoverEdge = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineBasicMaterial({ color: COLOR.selEdge, depthTest: false }),
    );
    this.hoverEdge.renderOrder = 20;
    this.scene.add(this.hoverEdge);
  }

  setEditingEnabled(enabled: boolean) {
    this.editingEnabled = enabled;
    if (!enabled) {
      this.finishDesignerDrag(true);
      this.cancelBodyResizePreview();
      this.cancelTransformPreview();
      this.cancelPushPullPreview();
      this.setHoverEdge(null);
      this.setHoverFace(null);
    }
  }

  setHoverFace(face: number | null) {
    if (this.hoverOverlay) {
      this.scene.remove(this.hoverOverlay);
      disposeObject(this.hoverOverlay);
      this.hoverOverlay = null;
    }
    if (face == null || !this.mesh) return;
    const range = this.faceRanges.find((r) => r.face_index === face);
    if (!range) return;
    const sub = subGeometry(this.mesh.geometry as THREE.BufferGeometry, range);
    const edges = new THREE.EdgesGeometry(sub, 1);
    sub.dispose();
    this.hoverOverlay = new THREE.LineSegments(
      edges, new THREE.LineBasicMaterial({ color: COLOR.hover })
    );
    this.scene.add(this.hoverOverlay);
  }

  setEdgeSelectionMode(active: boolean, edges: EdgeRef[]) {
    this.edgeSelectionActive = active;
    this.selectableEdges = edges;
    if (!active) this.renderer.domElement.style.cursor = "default";
  }

  // Подсветка выбранного ребра для edge feature: линия вдоль ребра (--sel-edge)
  // с маркерами концов; fallback — крест в середине.
  setEdgeMarker(edge: EdgeRef | null, labelText?: string) {
    if (this.edgeMarker) {
      this.scene.remove(this.edgeMarker);
      this.edgeMarker = null;
    }
    if (!edge) return;
    const [x, y, z] = docToThree(...edge.midpoint);
    const group = new THREE.Group();
    const mat = new THREE.LineBasicMaterial({ color: COLOR.selEdge });
    const points = edgePoints(edge);
    if (points.length > 2) {
      const geometry = new THREE.BufferGeometry().setFromPoints(points.map((point) => new THREE.Vector3(...docToThree(...point))));
      group.add(new THREE.Line(geometry, mat));
    }
    if (points.length <= 2 && edge.p0 && edge.p1) {
      const [ax, ay, az] = docToThree(...edge.p0);
      const [bx, by, bz] = docToThree(...edge.p1);
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute([ax, ay, az, bx, by, bz], 3));
      const line = new THREE.Line(g, mat);
      line.renderOrder = 18;
      group.add(line);
      for (const [px, py, pz] of [[ax, ay, az], [bx, by, bz]]) {
        const cap = new THREE.Mesh(
          new THREE.SphereGeometry(1.6, 12, 12),
          new THREE.MeshBasicMaterial({ color: COLOR.selEdge })
        );
        cap.position.set(px, py, pz);
        cap.renderOrder = 19;
        group.add(cap);
      }
    } else {
      const r = Math.max(2, Math.min(edge.length / 2, 6));
      for (const dir of [[1, 0, 0], [0, 1, 0], [0, 0, 1]] as const) {
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.Float32BufferAttribute([
          x - dir[0] * r, y - dir[1] * r, z - dir[2] * r,
          x + dir[0] * r, y + dir[1] * r, z + dir[2] * r,
        ], 3));
        const line = new THREE.Line(g, mat);
        line.renderOrder = 18;
        group.add(line);
      }
    }
    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(1.2, 12, 12),
      new THREE.MeshBasicMaterial({ color: COLOR.selEdge })
    );
    dot.position.set(x, y, z);
    dot.renderOrder = 18;
    group.add(dot);
    if (labelText) {
      const label = makeTextSprite(labelText);
      label.position.set(x, y + 7, z);
      group.add(label);
    }
    this.edgeMarker = group;
    this.scene.add(group);
  }

  setSelectedFace(face: number | null) {
    if (this.selOverlay) {
      this.scene.remove(this.selOverlay);
      disposeObject(this.selOverlay);
      this.selOverlay = null;
    }
    if (face == null || !this.mesh) return;
    const range = this.faceRanges.find((r) => r.face_index === face);
    if (!range) return;
    const sub = subGeometry(this.mesh.geometry as THREE.BufferGeometry, range);
    const mat = new THREE.MeshBasicMaterial({
      color: COLOR.selFace, transparent: true, opacity: 0.85,
      polygonOffset: true, polygonOffsetFactor: -2,
      side: THREE.DoubleSide,
    });
    this.selOverlay = new THREE.Mesh(sub, mat);
    this.selOverlay.renderOrder = 5;
    this.scene.add(this.selOverlay);
  }

  setSelectionHint(handler: ((label: string) => void) | null) { this.selectionHint = handler; }

  setPrintDiagnostics(profile: { x: number; y: number; z: number } | null, points: Size3[] = []) {
    if (this.printDiagnosticGroup) { this.scene.remove(this.printDiagnosticGroup); disposeObject(this.printDiagnosticGroup); this.printDiagnosticGroup = null; }
    if (!profile || !Object.values(profile).every((value) => Number.isFinite(value) && value > 0)) return;
    const group = new THREE.Group();
    const box = new THREE.BoxGeometry(profile.x, profile.z, profile.y);
    const outline = new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({ color: COLOR.hover, transparent: true, opacity: 0.7 }));
    box.dispose(); outline.position.y = profile.z / 2; group.add(outline);
    for (const point of points) {
      if (!point.every(Number.isFinite)) continue;
      const marker = new THREE.Mesh(new THREE.SphereGeometry(0.8, 12, 8), new THREE.MeshBasicMaterial({ color: 0xc4242a, depthTest: false }));
      marker.position.set(...docToThree(...point)); marker.renderOrder = 25; group.add(marker);
    }
    this.printDiagnosticGroup = group; this.scene.add(group); this.render();
  }

  setHiddenSolids(indices: number[]) {
    this.hiddenSolids = new Set(indices);
    if (!this.mesh) return;
    const geometry = this.mesh.geometry;
    const materials = Array.isArray(this.mesh.material) ? this.mesh.material : [this.mesh.material];
    if (materials.length === 1) this.mesh.material = [materials[0], new THREE.MeshBasicMaterial({ visible: false })];
    geometry.clearGroups();
    for (const range of this.faceRanges) geometry.addGroup(range.tri_start * 3, range.tri_count * 3, this.hiddenSolids.has(range.solid_index ?? -1) ? 1 : 0);
    for (const child of [...this.mesh.children]) { this.mesh.remove(child); disposeObject(child); }
    const visible = this.faceRanges.filter((range) => !this.hiddenSolids.has(range.solid_index ?? -1));
    if (visible.length) {
      const subset = subGeometryRanges(geometry, visible);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(subset, 15), new THREE.LineBasicMaterial({ color: COLOR.bodyEdge }));
      subset.dispose(); this.mesh.add(edges);
    }
    this.setHoverFace(null);
    this.selectionCycle = null;
    this.render();
  }

  setSelectedSolids(solidIndices: number[]) {
    if (this.selectedSolidsOverlay) {
      this.scene.remove(this.selectedSolidsOverlay);
      disposeObject(this.selectedSolidsOverlay);
      this.selectedSolidsOverlay = null;
    }
    if (!this.mesh || solidIndices.length === 0) return;
    const selected = new Set(solidIndices);
    const ranges = this.faceRanges.filter((range) =>
      range.solid_index != null && selected.has(range.solid_index));
    if (ranges.length === 0 && this.faceRanges.length > 0) return;
    const geometry = ranges.length ? subGeometryRanges(this.mesh.geometry as THREE.BufferGeometry, ranges) : this.mesh.geometry.clone();
    const material = new THREE.MeshBasicMaterial({
      color: COLOR.selBody,
      transparent: true,
      opacity: 0.28,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      side: THREE.DoubleSide,
    });
    this.selectedSolidsOverlay = new THREE.Mesh(geometry, material);
    this.selectedSolidsOverlay.renderOrder = 4;
    this.scene.add(this.selectedSolidsOverlay);
  }

  private pickBodyResizeHandle(event: PointerEvent): ResizeHandle | null {
    if (!this.bodyResizeGroup) return null;
    this.updatePointer(event);
    const hit = this.raycaster.intersectObject(this.bodyResizeGroup, true)
      .find((candidate) => candidate.object.userData.bodyResizeHandle != null);
    return (hit?.object.userData.bodyResizeHandle as ResizeHandle | undefined) ?? null;
  }

  setBodyResizeHandle(target: PartTransformTarget | null) {
    this.cancelBodyResizePreview();
    if (this.bodyResizeGroup) {
      this.scene.remove(this.bodyResizeGroup);
      disposeObject(this.bodyResizeGroup);
    }
    this.bodyResizeGroup = null;
    this.bodyResizeTarget = null;
    this.bodyResizeVertices.clear();
    if (!target || !this.mesh) return;
    const ranges = this.faceRanges.filter((range) => range.solid_index != null && target.solidIndices.includes(range.solid_index));
    const bounds = rangesBounds(this.mesh.geometry, ranges);
    if (!bounds) return;
    if (target.bbox?.length === 6 && target.bbox.every(Number.isFinite)) {
      const [minX, minY, minZ, maxX, maxY, maxZ] = target.bbox;
      bounds.min.set(...docToThree(minX, maxY, minZ));
      bounds.max.set(...docToThree(maxX, minY, maxZ));
    }
    const minimum: Size3 = [bounds.min.x, -bounds.max.z, bounds.min.y];
    const maximum: Size3 = [bounds.max.x, -bounds.min.z, bounds.max.y];
    const size = maximum.map((value, axis) => value - minimum[axis]) as Size3;
    if (!size.every((value) => Number.isFinite(value) && value > 1e-7)) return;
    this.bodyResizeTarget = { ...target, minimum, maximum, size };
    const indices = this.mesh.geometry.getIndex()!;
    for (const range of ranges) for (let index = range.tri_start * 3; index < (range.tri_start + range.tri_count) * 3; index += 1) {
      this.bodyResizeVertices.add(indices.getX(index));
    }
    const group = new THREE.Group();
    const outline = new THREE.Box3Helper(bounds, COLOR.selEdge);
    (outline.material as THREE.LineBasicMaterial).depthTest = false;
    outline.renderOrder = 24;
    group.add(outline);
    const addHandle = (handle: ResizeHandle) => {
      const position = size.map((_, axis) => handle.axis == null || axis === handle.axis
        ? handle.corner[axis] < 0 ? minimum[axis] : maximum[axis]
        : (minimum[axis] + maximum[axis]) / 2) as Size3;
      const color = handle.axis == null ? COLOR.selEdge : [COLOR.axisX, COLOR.axisY, COLOR.axisZ][handle.axis];
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({ color, depthTest: false }));
      mesh.position.set(...docToThree(...position));
      mesh.userData.bodyResizeHandle = handle;
      mesh.renderOrder = 28;
      group.add(mesh);
    };
    for (const sideX of [-1, 1] as const) for (const sideY of [-1, 1] as const) for (const sideZ of [-1, 1] as const) {
      addHandle({ corner: [sideX, sideY, sideZ], axis: null });
    }
    for (const axis of [0, 1, 2] as const) for (const side of [-1, 1] as const) {
      const corner: ResizeHandle["corner"] = [1, 1, 1];
      corner[axis] = side;
      addHandle({ corner, axis });
    }
    this.bodyResizeGroup = group;
    this.scene.add(group);
    this.updateBodyResizeHandleSizes();
    this.events.onBodyResizePreview(size);
    this.render();
  }

  private updateBodyResizeHandleSizes() {
    if (!this.bodyResizeGroup || !this.bodyResizeTarget) return;
    const target = this.bodyResizeTarget;
    const center = new THREE.Vector3(...docToThree(...target.size.map((_, axis) => (target.minimum[axis] + target.maximum[axis]) / 2) as Size3));
    const projected = center.clone().project(this.camera);
    const sample = projected.clone();
    sample.y += 16 / Math.max(1, this.renderer.domElement.clientHeight);
    const size = Math.max(0.01, sample.unproject(this.camera).distanceTo(center));
    for (const child of this.bodyResizeGroup.children) if (child.userData.bodyResizeHandle) {
      child.scale.set(size / this.bodyResizeGroup.scale.x, size / this.bodyResizeGroup.scale.y, size / this.bodyResizeGroup.scale.z);
    }
  }

  private previewBodyResize(handle: ResizeHandle, size: Size3) {
    const target = this.bodyResizeTarget;
    if (!target || !this.mesh || !this.bodyResizeGroup) return;
    if (!this.bodyResizeOriginal) {
      this.bodyResizeOriginal = this.mesh.geometry;
      this.bodyResizePreview = this.mesh.geometry.clone();
      this.mesh.geometry = this.bodyResizePreview;
    }
    const factor = size.map((value, axis) => value / target.size[axis]) as Size3;
    const anchor = resizeAnchor(handle).map((side, axis) => side < 0 ? target.minimum[axis] : target.maximum[axis]) as Size3;
    const origin = new THREE.Vector3(...docToThree(...anchor));
    const scale = new THREE.Vector3(factor[0], factor[2], factor[1]);
    const original = this.bodyResizeOriginal.getAttribute("position");
    const positions = this.mesh.geometry.getAttribute("position") as THREE.BufferAttribute;
    const point = new THREE.Vector3();
    for (const vertex of this.bodyResizeVertices) {
      point.fromBufferAttribute(original, vertex).sub(origin).multiply(scale).add(origin);
      positions.setXYZ(vertex, point.x, point.y, point.z);
    }
    positions.needsUpdate = true;
    this.mesh.geometry.computeVertexNormals();
    this.mesh.geometry.computeBoundingSphere();
    this.bodyResizeGroup.scale.copy(scale);
    this.bodyResizeGroup.position.copy(origin.clone().multiply(new THREE.Vector3(1 - scale.x, 1 - scale.y, 1 - scale.z)));
    this.updateBodyResizeHandleSizes();
    for (const child of this.mesh.children) child.visible = false;
    if (this.selOverlay) this.selOverlay.visible = false;
    if (this.selectedSolidsOverlay) this.selectedSolidsOverlay.visible = false;
    if (this.dimGroup) this.dimGroup.visible = false;
    if (this.bodyResizeLabel) { this.scene.remove(this.bodyResizeLabel); disposeObject(this.bodyResizeLabel); }
    const label = makeTextSprite(sizeLabel(size));
    label.position.copy(origin.clone().add(new THREE.Vector3(...docToThree(...resizeDirection(size, handle))).multiplyScalar(Math.max(...size))));
    label.position.y += 8;
    this.bodyResizeLabel = label;
    this.scene.add(label);
    this.render();
  }

  cancelBodyResizePreview() {
    const drag = this.bodyResizeDrag;
    this.bodyResizeDrag = null;
    if (drag) {
      this.controls.enabled = true;
      if (this.renderer.domElement.hasPointerCapture(drag.pointerId)) this.renderer.domElement.releasePointerCapture(drag.pointerId);
    }
    if (this.bodyResizeOriginal && this.mesh) this.mesh.geometry = this.bodyResizeOriginal;
    this.bodyResizeOriginal = null;
    this.bodyResizePreview?.dispose(); this.bodyResizePreview = null;
    if (this.bodyResizeGroup) { this.bodyResizeGroup.scale.set(1, 1, 1); this.bodyResizeGroup.position.set(0, 0, 0); }
    if (this.mesh) for (const child of this.mesh.children) child.visible = true;
    if (this.selOverlay) this.selOverlay.visible = true;
    if (this.selectedSolidsOverlay) this.selectedSolidsOverlay.visible = true;
    if (this.dimGroup) this.dimGroup.visible = true;
    if (this.bodyResizeLabel) { this.scene.remove(this.bodyResizeLabel); disposeObject(this.bodyResizeLabel); this.bodyResizeLabel = null; }
    this.renderer.domElement.style.cursor = "default";
    this.events.onBodyResizePreview(null);
  }

  setTransformHandle(target: PartTransformTarget | null) {
    if (this.transformGroup) {
      this.scene.remove(this.transformGroup);
      disposeObject(this.transformGroup);
      this.transformGroup = null;
    }
    this.transformLabel = null;
    this.transformTarget = null;
    if (!target || !this.mesh || target.solidIndices.length === 0) return;

    const selected = new Set(target.solidIndices);
    const ranges = this.faceRanges.filter((range) =>
      range.solid_index != null && selected.has(range.solid_index));
    const bounds = rangesBounds(this.mesh.geometry as THREE.BufferGeometry, ranges) ??
      (this.faceRanges.length === 0 ? new THREE.Box3().setFromBufferAttribute(this.mesh.geometry.getAttribute("position") as THREE.BufferAttribute) : null);
    if (!bounds) return;
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const length = Math.max(28, Math.min(48, size.length() * 0.32));
    const group = new THREE.Group();
    const colors: Record<TransformAxis, number> = {
      x: COLOR.axisX,
      y: COLOR.axisY,
      z: COLOR.axisZ,
    };
    for (const axis of ["x", "y", "z"] as const) {
      const [dx, dy, dz] = docToThree(...axisVector(axis));
      const direction = new THREE.Vector3(dx, dy, dz).normalize();
      const arrow = new THREE.ArrowHelper(direction, center, length, colors[axis], 4.5, 2.5);
      (arrow.line.material as THREE.LineBasicMaterial).depthTest = false;
      (arrow.cone.material as THREE.MeshBasicMaterial).depthTest = false;
      arrow.line.renderOrder = 25;
      arrow.cone.renderOrder = 26;
      arrow.cone.userData.transformAxis = axis;
      group.add(arrow);

      const hit = new THREE.Mesh(
        new THREE.CylinderGeometry(3.2, 3.2, length, 12),
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthTest: false }),
      );
      hit.position.copy(center.clone().addScaledVector(direction, length / 2));
      hit.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
      hit.userData.transformAxis = axis;
      hit.renderOrder = 27;
      group.add(hit);
    }
    this.transformTarget = { ...target, center };
    this.transformGroup = group;
    this.scene.add(group);
    this.render();
  }

  setSplitPreview(plane: "XY" | "XZ" | "YZ" | null, offset = 0, solidIndices: number[] = []) {
    if (this.splitPreview) {
      this.scene.remove(this.splitPreview);
      disposeObject(this.splitPreview);
      this.splitPreview = null;
    }
    if (!plane || !this.mesh) return;
    const ranges = this.faceRanges.filter((range) => range.solid_index != null && solidIndices.includes(range.solid_index));
    const bounds = rangesBounds(this.mesh.geometry as THREE.BufferGeometry, ranges);
    if (!bounds) return;
    const center = bounds.getCenter(new THREE.Vector3());
    const size = Math.max(10, bounds.getSize(new THREE.Vector3()).length() * 1.3);
    const normal = plane === "YZ" ? new THREE.Vector3(1, 0, 0)
      : plane === "XZ" ? new THREE.Vector3(0, 0, -1) : new THREE.Vector3(0, 1, 0);
    if (plane === "YZ") center.x = offset;
    else if (plane === "XZ") center.z = -offset;
    else center.y = offset;
    this.splitPreview = new THREE.Mesh(
      new THREE.PlaneGeometry(size, size),
      new THREE.MeshBasicMaterial({ color: 0x2563eb, transparent: true, opacity: 0.22, depthWrite: false, side: THREE.DoubleSide }),
    );
    this.splitPreview.position.copy(center);
    this.splitPreview.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
    this.splitPreview.renderOrder = 8;
    this.scene.add(this.splitPreview);
  }

  setTransformPreview(axis: TransformAxis, delta: number) {
    if (!this.transformTarget || !this.transformGroup) return;
    const [dx, dy, dz] = docToThree(...axisVector(axis));
    const offset = new THREE.Vector3(dx, dy, dz).multiplyScalar(delta);
    this.transformGroup.position.copy(offset);
    if (this.selectedSolidsOverlay) this.selectedSolidsOverlay.position.copy(offset);
    if (this.selOverlay) this.selOverlay.position.copy(offset);
    if (this.transformLabel) {
      this.transformGroup.remove(this.transformLabel);
      disposeObject(this.transformLabel);
      this.transformLabel = null;
    }
    if (Math.abs(delta) >= 0.05) {
      const sign = delta > 0 ? "+" : "";
      const label = makeTextSprite(`${axis.toUpperCase()} ${sign}${Math.round(delta * 10) / 10} мм`);
      label.position.copy(this.transformTarget.center.clone().add(new THREE.Vector3(0, 10, 0)));
      this.transformGroup.add(label);
      this.transformLabel = label;
    }
    this.render();
  }

  cancelTransformPreview() {
    if (this.snapGuide) { this.scene.remove(this.snapGuide); disposeObject(this.snapGuide); this.snapGuide = null; }
    if (this.transformDrag) {
      const pointerId = this.transformDrag.pointerId;
      this.transformDrag = null;
      this.controls.enabled = true;
      if (this.renderer.domElement.hasPointerCapture(pointerId)) this.renderer.domElement.releasePointerCapture(pointerId);
    }
    if (this.transformGroup) this.transformGroup.position.set(0, 0, 0);
    if (this.selectedSolidsOverlay) this.selectedSolidsOverlay.position.set(0, 0, 0);
    if (this.selOverlay) this.selOverlay.position.set(0, 0, 0);
    if (this.transformGroup && this.transformLabel) {
      this.transformGroup.remove(this.transformLabel);
      disposeObject(this.transformLabel);
    }
    this.transformLabel = null;
    this.render();
  }

  setPushPullHandle(target: FaceEditTarget | null) {
    if (this.pushPullGroup) {
      this.scene.remove(this.pushPullGroup);
      disposeObject(this.pushPullGroup);
      this.pushPullGroup = null;
    }
    this.pushPullLabel = null;
    this.pushPullTarget = target;
    if (!target) return;

    const [cx, cy, cz] = docToThree(...target.center);
    const [nx, ny, nz] = docToThree(...target.normal);
    const origin = new THREE.Vector3(cx, cy, cz);
    const direction = new THREE.Vector3(nx, ny, nz).normalize();
    const length = 14;
    const group = new THREE.Group();
    const arrow = new THREE.ArrowHelper(direction, origin, length, COLOR.selFace, 4.5, 2.5);
    (arrow.line.material as THREE.LineBasicMaterial).depthTest = false;
    (arrow.line.material as THREE.LineBasicMaterial).depthWrite = false;
    (arrow.cone.material as THREE.MeshBasicMaterial).depthTest = false;
    (arrow.cone.material as THREE.MeshBasicMaterial).depthWrite = false;
    arrow.line.renderOrder = 21;
    arrow.cone.renderOrder = 21;
    arrow.cone.userData.pushPullHandle = true;
    group.add(arrow);

    const stemLength = length - 3;
    const stem = new THREE.Mesh(
      new THREE.CylinderGeometry(0.65, 0.65, stemLength, 12),
      new THREE.MeshBasicMaterial({ color: 0x211f1d, depthTest: false, depthWrite: false }),
    );
    stem.position.copy(origin.clone().addScaledVector(direction, stemLength / 2));
    stem.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
    stem.renderOrder = 20;
    group.add(stem);

    const tipPosition = origin.clone().addScaledVector(direction, length);
    const tipOutline = new THREE.Mesh(
      new THREE.SphereGeometry(3.6, 20, 20),
      new THREE.MeshBasicMaterial({ color: 0x211f1d, depthTest: false, depthWrite: false }),
    );
    tipOutline.position.copy(tipPosition);
    tipOutline.userData.pushPullHandle = true;
    tipOutline.renderOrder = 22;
    group.add(tipOutline);
    const tip = new THREE.Mesh(
      new THREE.SphereGeometry(2.6, 20, 20),
      new THREE.MeshBasicMaterial({ color: COLOR.selFace, depthTest: false, depthWrite: false }),
    );
    tip.position.copy(tipPosition);
    tip.userData.pushPullHandle = true;
    tip.renderOrder = 23;
    group.add(tip);
    const hit = new THREE.Mesh(
      new THREE.SphereGeometry(5, 16, 16),
      new THREE.MeshBasicMaterial({ color: COLOR.selFace, transparent: true, opacity: 0, depthTest: false, depthWrite: false }),
    );
    hit.position.copy(tipPosition);
    hit.userData.pushPullHandle = true;
    hit.renderOrder = 24;
    group.add(hit);
    this.pushPullGroup = group;
    this.scene.add(group);
  }

  setPushPullPreview(delta: number) {
    if (!this.pushPullTarget || !this.pushPullGroup) return;
    const [nx, ny, nz] = docToThree(...this.pushPullTarget.normal);
    const offset = new THREE.Vector3(nx, ny, nz).normalize().multiplyScalar(delta);
    this.pushPullGroup.position.copy(offset);
    if (this.selOverlay) this.selOverlay.position.copy(offset);
    if (this.pushPullLabel) {
      this.pushPullGroup.remove(this.pushPullLabel);
      disposeObject(this.pushPullLabel);
      this.pushPullLabel = null;
    }
    if (Math.abs(delta) >= 0.05) {
      const sign = delta > 0 ? "+" : "";
      const label = makeTextSprite(`${sign}${Math.round(delta * 10) / 10} мм`);
      const [cx, cy, cz] = docToThree(...this.pushPullTarget.center);
      label.position.set(cx, cy + 10, cz);
      label.renderOrder = 24;
      this.pushPullLabel = label;
      this.pushPullGroup.add(label);
    }
    this.render();
  }

  cancelPushPullPreview() {
    if (this.pushPullDrag) {
      const pointerId = this.pushPullDrag.pointerId;
      this.pushPullDrag = null;
      this.controls.enabled = true;
      if (this.renderer.domElement.hasPointerCapture(pointerId)) this.renderer.domElement.releasePointerCapture(pointerId);
    }
    if (this.pushPullGroup) this.pushPullGroup.position.set(0, 0, 0);
    if (this.selOverlay) this.selOverlay.position.set(0, 0, 0);
    if (this.pushPullGroup && this.pushPullLabel) {
      this.pushPullGroup.remove(this.pushPullLabel);
      disposeObject(this.pushPullLabel);
    }
    this.pushPullLabel = null;
    this.render();
  }

  setFaceFeaturePreview(preview: FaceFeaturePreview | null) {
    if (this.faceFeatureGroup) {
      this.scene.remove(this.faceFeatureGroup);
      disposeObject(this.faceFeatureGroup);
      this.faceFeatureGroup = null;
    }
    if (!preview) {
      this.render();
      return;
    }

    const { target, args } = preview;
    const depth = args.depth === "through" ? target.axisSpan + 2 : args.depth;
    const geometry = new THREE.ExtrudeGeometry(faceFeatureShape(args.profile), {
      depth,
      bevelEnabled: false,
      curveSegments: 32,
    });
    const directionSign = args.mode === "add" ? 1 : -1;
    const normalDoc = target.normal.map((value) => value * directionSign) as [number, number, number];
    const uDoc = axisVector(target.uAxis);
    const vDoc: [number, number, number] = [
      normalDoc[1] * uDoc[2] - normalDoc[2] * uDoc[1],
      normalDoc[2] * uDoc[0] - normalDoc[0] * uDoc[2],
      normalDoc[0] * uDoc[1] - normalDoc[1] * uDoc[0],
    ];
    const uThree = new THREE.Vector3(...docToThree(...uDoc));
    const vThree = new THREE.Vector3(...docToThree(...vDoc));
    const normalThree = new THREE.Vector3(...docToThree(...normalDoc));
    geometry.applyMatrix4(new THREE.Matrix4().makeBasis(uThree, vThree, normalThree));

    const profileCenter = args.profile.center;
    const vOffsetAxis = axisVector(target.vAxis);
    const centerDoc: [number, number, number] = [
      target.center[0] + uDoc[0] * profileCenter[0] + vOffsetAxis[0] * profileCenter[1],
      target.center[1] + uDoc[1] * profileCenter[0] + vOffsetAxis[1] * profileCenter[1],
      target.center[2] + uDoc[2] * profileCenter[0] + vOffsetAxis[2] * profileCenter[1],
    ];
    geometry.translate(...docToThree(...centerDoc));

    const group = new THREE.Group();
    const color = args.mode === "add" ? COLOR.selFace : 0xb91c1c;
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: args.mode === "add" ? 0.34 : 0.24,
      depthWrite: false,
      side: THREE.DoubleSide,
    }));
    mesh.renderOrder = 12;
    group.add(mesh);
    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry, 12),
      new THREE.LineBasicMaterial({ color, depthTest: false }),
    );
    outline.renderOrder = 13;
    group.add(outline);
    const label = makeTextSprite(args.mode === "add" ? `+${depth} мм` : `−${depth} мм`);
    const labelPosition = new THREE.Vector3(...docToThree(...centerDoc));
    label.position.copy(labelPosition.add(new THREE.Vector3(0, 10, 0)));
    group.add(label);
    this.faceFeatureGroup = group;
    this.scene.add(group);
    this.render();
  }

  setFaceDomePreview(preview: FaceDomePreview | null) {
    if (this.faceDomeGroup) {
      this.scene.remove(this.faceDomeGroup);
      disposeObject(this.faceDomeGroup);
      this.faceDomeGroup = null;
    }
    if (!preview) {
      this.render();
      return;
    }

    const { target, args } = preview;
    const geometry = faceDomeGeometry(args.diameter, args.height);
    const directionSign = args.mode === "add" ? 1 : -1;
    const normalDoc = target.normal.map((value) => value * directionSign) as [number, number, number];
    const uDoc = axisVector(target.uAxis);
    const vDoc: [number, number, number] = [
      normalDoc[1] * uDoc[2] - normalDoc[2] * uDoc[1],
      normalDoc[2] * uDoc[0] - normalDoc[0] * uDoc[2],
      normalDoc[0] * uDoc[1] - normalDoc[1] * uDoc[0],
    ];
    geometry.applyMatrix4(new THREE.Matrix4().makeBasis(
      new THREE.Vector3(...docToThree(...uDoc)),
      new THREE.Vector3(...docToThree(...vDoc)),
      new THREE.Vector3(...docToThree(...normalDoc)),
    ));

    const vOffsetAxis = axisVector(target.vAxis);
    const centerDoc: [number, number, number] = [
      target.center[0] + uDoc[0] * args.center[0] + vOffsetAxis[0] * args.center[1],
      target.center[1] + uDoc[1] * args.center[0] + vOffsetAxis[1] * args.center[1],
      target.center[2] + uDoc[2] * args.center[0] + vOffsetAxis[2] * args.center[1],
    ];
    geometry.translate(...docToThree(...centerDoc));

    const group = new THREE.Group();
    const color = args.mode === "add" ? COLOR.selFace : 0xb91c1c;
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: args.mode === "add" ? 0.36 : 0.25,
      depthWrite: false,
      side: THREE.DoubleSide,
    }));
    mesh.renderOrder = 12;
    group.add(mesh);
    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry, 12),
      new THREE.LineBasicMaterial({ color, depthTest: false }),
    );
    outline.renderOrder = 13;
    group.add(outline);
    const label = makeTextSprite(`${args.mode === "add" ? "+" : "−"}${args.height} мм`);
    label.position.copy(new THREE.Vector3(...docToThree(...centerDoc)).add(new THREE.Vector3(0, 10, 0)));
    group.add(label);
    this.faceDomeGroup = group;
    this.scene.add(group);
    this.render();
  }

  setSheetBendPreview(preview: SheetBendPreview | null) {
    if (this.sheetBendGroup) {
      this.scene.remove(this.sheetBendGroup);
      disposeObject(this.sheetBendGroup);
      this.sheetBendGroup = null;
    }
    if (!preview) {
      this.render();
      return;
    }
    const geometry = sheetBendGeometry(preview);
    const group = new THREE.Group();
    const color = 0x2563eb;
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.3,
      depthWrite: false,
      side: THREE.DoubleSide,
    }));
    mesh.renderOrder = 12;
    group.add(mesh);
    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry, 10),
      new THREE.LineBasicMaterial({ color, depthTest: false }),
    );
    outline.renderOrder = 13;
    group.add(outline);
    const label = makeTextSprite(
      `${preview.bends.length} ${preview.bends.length === 1 ? "изгиб" : "изгиба"} · ${preview.args.angle}°  R${preview.args.inside_radius}`,
    );
    const bounds = new THREE.Box3().setFromBufferAttribute(
      geometry.getAttribute("position") as THREE.BufferAttribute,
    );
    const labelPosition = bounds.getCenter(new THREE.Vector3());
    labelPosition.y = bounds.max.y + 8;
    label.position.copy(labelPosition);
    group.add(label);
    this.sheetBendGroup = group;
    this.scene.add(group);
    this.render();
  }

  setMesh(data: MeshData | null) {
    this.setOperationPreview(null);
    this.setDesignerTool(null);
    this.designerPull = null;
    this.dimensionData = data;
    this.setBodyResizeHandle(null);
    this.cancelTransformPreview();
    this.cancelPushPullPreview();
    this.setHoverEdge(null);
    if (this.mesh) {
      this.scene.remove(this.mesh);
      this.mesh.geometry.dispose();
      this.mesh = null;
    }
    this.setHoverFace(null);
    this.setSelectedFace(null);
    this.setEdgeMarker(null);
    this.setSelectedSolids([]);
    this.setTransformHandle(null);
    this.setPushPullHandle(null);
    this.setFaceFeaturePreview(null);
    this.setFaceDomePreview(null);
    this.setSheetBendPreview(null);
    this.faceRanges = data?.face_ranges ?? [];
    if (!data) {
      this.rebuildDimensions(null);
      return;
    }
    const pos = mapMeshPositionsForViewport(data.positions);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const indices = data.indices instanceof Uint32Array ? data.indices : new Uint32Array(data.indices);
    geo.setIndex(new THREE.BufferAttribute(indices, 1));
    geo.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({ color: COLOR.body, roughness: 0.75, metalness: 0.05 });
    this.mesh = new THREE.Mesh(geo, mat);
    this.scene.add(this.mesh);
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geo, 15),
      new THREE.LineBasicMaterial({ color: COLOR.bodyEdge })
    );
    this.mesh.add(edges);
    this.rebuildDimensions(data);
  }

  private rebuildDimensions(data: MeshData | null) {
    if (this.dimGroup) {
      this.scene.remove(this.dimGroup);
      disposeObject(this.dimGroup);
      this.dimGroup = null;
    }
    if (!data || !data.positions.length) return;
    const p = data.positions;
    let minX = Infinity, minY = Infinity, minZ = Infinity, maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
    for (let i = 0; i < p.length; i += 3) {
      minX = Math.min(minX, p[i]); maxX = Math.max(maxX, p[i]);
      minY = Math.min(minY, p[i + 1]); maxY = Math.max(maxY, p[i + 1]);
      minZ = Math.min(minZ, p[i + 2]); maxZ = Math.max(maxZ, p[i + 2]);
    }
    if (this.dimensionBounds?.length === 6) [minX, minY, minZ, maxX, maxY, maxZ] = this.dimensionBounds;
    const fmt = (v: number) => `${Math.round(v * 100) / 100} мм`;
    const group = new THREE.Group();
    const lineMat = new THREE.LineBasicMaterial({ color: COLOR.dim });
    const seg = (a: [number, number, number], b: [number, number, number]) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute([...a, ...b], 3));
      const l = new THREE.Line(g, lineMat);
      l.renderOrder = 15;
      group.add(l);
    };
    const tick = (at: [number, number, number], dir: [number, number, number], len = 3) => {
      seg(
        [at[0] - dir[0] * len, at[1] - dir[1] * len, at[2] - dir[2] * len],
        [at[0] + dir[0] * len, at[1] + dir[1] * len, at[2] + dir[2] * len]
      );
    };
    const label = (text: string, at: [number, number, number]) => {
      const s = makeTextSprite(text);
      s.userData.dimensionAxis = group.children.filter((child) => child instanceof THREE.Sprite).length;
      s.position.set(...at);
      group.add(s);
    };
    const gap = 16;
    const zLow = minZ;
    // длина (X) — перед деталью
    const yLine = minY - gap;
    const [ax0, ay0, az0] = docToThree(minX, yLine, zLow);
    const [ax1] = docToThree(maxX, yLine, zLow);
    seg([ax0, ay0, az0], [ax1, ay0, az0]);
    tick([ax0, ay0, az0], [0, 1, 0]); tick([ax1, ay0, az0], [0, 1, 0]);
    label(fmt(maxX - minX), [(ax0 + ax1) / 2, ay0 + 6, az0]);
    // ширина (Y) — сбоку
    const xLine = maxX + gap;
    const [bx0, by0, bz0] = docToThree(xLine, minY, zLow);
    const [, , bz1] = docToThree(xLine, maxY, zLow);
    seg([bx0, by0, bz0], [bx0, by0, bz1]);
    tick([bx0, by0, bz0], [0, 1, 0]); tick([bx0, by0, bz1], [0, 1, 0]);
    label(fmt(maxY - minY), [bx0, by0 + 6, (bz0 + bz1) / 2]);
    // толщина (Z) — вертикально у угла
    const cx = maxX + gap, cy = maxY + gap;
    const [cx0, cy0, cz0] = docToThree(cx, cy, minZ);
    const [, cy1] = docToThree(cx, cy, maxZ);
    seg([cx0, cy0, cz0], [cx0, cy1, cz0]);
    tick([cx0, cy0, cz0], [1, 0, 0]); tick([cx0, cy1, cz0], [1, 0, 0]);
    label(fmt(maxZ - minZ), [cx0, (cy0 + cy1) / 2, cz0 + 10]);

    this.dimGroup = group;
    this.scene.add(group);
  }

  setDimensionEditor(bounds: number[] | null, edit: ((axis: number) => void) | null) {
    this.dimensionBounds = bounds; this.dimensionEdit = edit;
    this.rebuildDimensions(this.dimensionData); this.render();
  }

  private pickDimension(event: PointerEvent): number | null {
    if (!this.dimGroup || !this.dimensionEdit) return null;
    this.updatePointer(event);
    return this.raycaster.intersectObject(this.dimGroup, true).find((item) => item.object.userData.dimensionAxis != null)?.object.userData.dimensionAxis ?? null;
  }

  setDesignerContext(handler: ((x: number, y: number) => void) | null) { this.designerContext = handler; }
  setDesignerPull(target: FaceEditTarget | null, handler: ((delta: number, commit: boolean) => void) | null) {
    this.designerPull = handler; this.setPushPullHandle(target);
  }
  setResizeConstraint(value: string) { this.resizeConstraint = value; }
  setSnapping(settings: { bounds: number[]; others: number[][]; grid: number } | null) { this.snapSettings = settings; }

  setOperationPreview(data: MeshData | null) {
    if (this.operationPreview) { this.scene.remove(this.operationPreview); disposeObject(this.operationPreview); this.operationPreview = null; }
    if (this.mesh) this.mesh.visible = !data;
    if (this.selOverlay) this.selOverlay.visible = !data;
    if (this.selectedSolidsOverlay) this.selectedSolidsOverlay.visible = !data;
    if (data) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(mapMeshPositionsForViewport(data.positions), 3));
      geometry.setIndex(new THREE.BufferAttribute(Uint32Array.from(data.indices), 1));
      geometry.computeVertexNormals();
      this.operationPreview = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0x91b4c7, roughness: 0.75, side: THREE.DoubleSide }));
      this.scene.add(this.operationPreview);
    }
    this.render();
  }

  setDesignerTool(tool: DesignerPointerTool | null) {
    this.finishDesignerDrag(true);
    if (this.designerMarker) { this.scene.remove(this.designerMarker); disposeObject(this.designerMarker); this.designerMarker = null; }
    this.designerTool = tool;
    if (tool?.origin) {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(tool.kind === "edge" ? 2 : 0.8, 16, 8),
        new THREE.MeshBasicMaterial({ color: 0x2563eb, depthTest: false }));
      marker.position.set(...docToThree(...tool.origin)); marker.renderOrder = 30;
      this.designerMarker = marker; this.scene.add(marker);
    } else if (tool?.kind === "sculpt" && Number.isFinite(tool.radius) && tool.radius! > 0) {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(tool.radius, 24, 12), new THREE.MeshBasicMaterial({ color: 0x2563eb, wireframe: true, transparent: true, opacity: 0.25, depthTest: false }));
      marker.visible = false; marker.renderOrder = 30; this.designerMarker = marker; this.scene.add(marker);
    }
    this.render();
  }

  private finishDesignerDrag(cancelled: boolean) {
    const drag = this.designerDrag;
    if (!drag) return;
    this.designerDrag = null;
    this.controls.enabled = true;
    if (this.renderer.domElement.hasPointerCapture(drag.pointerId)) this.renderer.domElement.releasePointerCapture(drag.pointerId);
    this.designerTool?.finish(cancelled);
  }

  handleModelingKey(event: KeyboardEvent): boolean {
    if (this.designerDrag && this.designerTool?.numeric && !event.ctrlKey && !event.metaKey && !event.altKey) {
      if (event.key === "Escape" || event.key === "Enter") { this.finishDesignerDrag(event.key === "Escape"); return true; }
      if (!/^[0-9.,]$/.test(event.key) && event.key !== "Backspace") return false;
      this.numericDrag = event.key === "Backspace" ? this.numericDrag.slice(0, -1) : this.numericDrag + event.key.replace(",", ".");
      const value = Number(this.numericDrag);
      if (this.numericDrag && Number.isFinite(value) && value > 0) this.designerTool.numeric(value);
      return true;
    }
    const active = this.bodyResizeDrag ?? this.transformDrag ?? this.pushPullDrag;
    if (!active || event.ctrlKey || event.metaKey || event.altKey) return false;
    if (event.key === "Escape") {
      this.cancelBodyResizePreview(); this.cancelTransformPreview(); this.cancelPushPullPreview();
      this.numericDrag = ""; return true;
    }
    if (event.key === "Enter") {
      this.onPointerUp({ pointerId: active.pointerId, button: 0, preventDefault() {}, stopPropagation() {} } as PointerEvent);
      return true;
    }
    if (!/^[0-9.,-]$/.test(event.key) && event.key !== "Backspace") return false;
    this.numericDrag = event.key === "Backspace" ? this.numericDrag.slice(0, -1) : this.numericDrag + event.key.replace(",", ".");
    const value = Number(this.numericDrag);
    if (!this.numericDrag || !Number.isFinite(value)) return true;
    if (this.bodyResizeDrag && this.bodyResizeTarget && value > 0) {
      const drag = this.bodyResizeDrag, size = this.bodyResizeTarget.size;
      drag.size = drag.handle.axis == null ? size.map((item) => item * value / Math.max(...size)) as Size3
        : constrainedSize(size, drag.handle.axis, value, this.resizeConstraint);
      this.previewBodyResize(drag.handle, drag.size); this.events.onBodyResizePreview(drag.size);
    } else if (this.transformDrag) {
      this.transformDrag.delta = value; this.setTransformPreview(this.transformDrag.axis, value);
      this.events.onPartMovePreview(this.transformDrag.axis, value);
    } else if (this.pushPullDrag) {
      this.pushPullDrag.delta = value;
      if (this.designerPull) this.designerPull(value, false);
      else { this.setPushPullPreview(value); this.events.onPushPullPreview(value); }
    }
    return true;
  }

  setView(name: ViewName) {
    const d = Math.max(this.persp.position.distanceTo(this.controls.target), 150);
    const t = this.controls.target;
    const positions: Record<ViewName, [number, number, number]> = {
      top: [t.x, d, t.z],
      front: [t.x, t.y, t.z + d],
      side: [t.x + d, t.y, t.z],
      iso: [t.x + d * 0.6, t.y + d * 0.55, t.z + d * 0.6],
    };
    this.persp.position.set(...positions[name]);
    this.ortho.position.set(...positions[name]);
    this.controls.update();
    this.render();
  }

  fit() {
    if (!this.mesh) return;
    const box = new THREE.Box3().setFromObject(this.mesh);
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const radius = Math.max(size.x, size.y, size.z) * 0.9 + 10;
    const dir = this.persp.position.clone().sub(this.controls.target).normalize();
    this.controls.target.copy(center);
    this.persp.position.copy(center.clone().add(dir.multiplyScalar(radius * 2.2)));
    this.halfSize = radius;
    this.updateOrthoFrustum();
    this.ortho.position.copy(this.persp.position);
    this.controls.update();
    this.render();
  }

  toggleProjection(): boolean {
    this.orthoMode = !this.orthoMode;
    if (this.orthoMode) {
      this.ortho.position.copy(this.persp.position);
      this.camera = this.ortho;
    } else {
      this.persp.position.copy(this.ortho.position);
      this.camera = this.persp;
    }
    const target = this.controls.target.clone();
    this.controls.dispose();
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.configureControls();
    this.controls.target.copy(target);
    this.controls.update();
    this.render();
    return this.orthoMode;
  }

  dispose() {
    this.setDesignerTool(null);
    this.setOperationPreview(null);
    if (this.dimGroup) { this.scene.remove(this.dimGroup); disposeObject(this.dimGroup); this.dimGroup = null; }
    this.setBodyResizeHandle(null);
    this.setHoverEdge(null);
    this.setSplitPreview(null);
    this.setTransformHandle(null);
    this.setSelectedSolids([]);
    this.setFaceFeaturePreview(null);
    this.setFaceDomePreview(null);
    this.setSheetBendPreview(null);
    this.resizeObs.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}

// Площадь грани по треугольникам (координаты документа, мм²)
export function faceArea(data: MeshData, faceIndex: number): number {
  const range = data.face_ranges.find((r) => r.face_index === faceIndex);
  if (!range) return 0;
  const p = data.positions;
  const idx = data.indices;
  let area = 0;
  for (let t = range.tri_start; t < range.tri_start + range.tri_count; t++) {
    const a = idx[t * 3] * 3, b = idx[t * 3 + 1] * 3, c = idx[t * 3 + 2] * 3;
    const abx = p[b] - p[a], aby = p[b + 1] - p[a + 1], abz = p[b + 2] - p[a + 2];
    const acx = p[c] - p[a], acy = p[c + 1] - p[a + 1], acz = p[c + 2] - p[a + 2];
    const cx = aby * acz - abz * acy;
    const cy = abz * acx - abx * acz;
    const cz = abx * acy - aby * acx;
    area += Math.sqrt(cx * cx + cy * cy + cz * cz) / 2;
  }
  return area;
}
