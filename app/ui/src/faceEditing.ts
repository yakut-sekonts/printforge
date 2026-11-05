import type {
  FaceAxis, FaceDomeArgs, FaceFeatureArgs, FaceFeatureProfile, FaceOffsetRef, MeshData, PartDef, SheetBendArgs,
  TemplateDef,
} from "./types";

export interface FaceAnalysis {
  faceIndex: number;
  area: number;
  center: [number, number, number];
  normal: [number, number, number];
  axis: FaceAxis | null;
  side: -1 | 1;
  planar: boolean;
  atBoundary: boolean;
  axisSpan: number;
}

export interface FaceEditTarget extends FaceAnalysis {
  partId: string;
  mode?: "parameter" | "offset";
  faceRef?: FaceOffsetRef;
  parameter: string;
  label: string;
  current: number;
  minimum: number;
  deltaFactor: number;
  symmetric: boolean;
}

export interface FaceFeatureTarget extends FaceAnalysis {
  partId: string;
  uAxis: FaceAxis;
  vAxis: FaceAxis;
  uLabel: string;
  vLabel: string;
  anchor: [number, number];
}

export interface FaceFeaturePreview {
  target: FaceFeatureTarget;
  args: FaceFeatureArgs;
}

export interface FaceDomePreview {
  target: FaceFeatureTarget;
  args: FaceDomeArgs;
}

export interface SheetBendPreview {
  target: FaceFeatureTarget;
  args: SheetBendArgs;
  bends: SheetBendArgs[];
  length: number;
  width: number;
  thickness: number;
}

const AXIS_INDEX: Record<FaceAxis, 0 | 1 | 2> = { x: 0, y: 1, z: 2 };

function normalize(vector: [number, number, number]): [number, number, number] {
  const length = Math.hypot(vector[0], vector[1], vector[2]);
  return length > 1e-12
    ? [vector[0] / length, vector[1] / length, vector[2] / length]
    : [0, 0, 0];
}

function meshBounds(mesh: MeshData, solidIndices?: number[]): {
  min: [number, number, number];
  max: [number, number, number];
} | null {
  const min: [number, number, number] = [Infinity, Infinity, Infinity];
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity];
  const selected = solidIndices == null ? null : new Set(solidIndices);
  const vertices = new Set<number>();
  if (selected) {
    for (const range of mesh.face_ranges) {
      if (range.solid_index == null || !selected.has(range.solid_index)) continue;
      for (let triangle = range.tri_start; triangle < range.tri_start + range.tri_count; triangle += 1) {
        for (let corner = 0; corner < 3; corner += 1) vertices.add(mesh.indices[triangle * 3 + corner]);
      }
    }
  } else {
    for (let vertex = 0; vertex < mesh.positions.length / 3; vertex += 1) vertices.add(vertex);
  }
  if (vertices.size === 0) return null;
  for (const vertex of vertices) {
    for (let axis = 0; axis < 3; axis += 1) {
      min[axis] = Math.min(min[axis], mesh.positions[vertex * 3 + axis]);
      max[axis] = Math.max(max[axis], mesh.positions[vertex * 3 + axis]);
    }
  }
  return { min, max };
}

export function analyzeFace(mesh: MeshData, faceIndex: number, solidIndices?: number[]): FaceAnalysis | null {
  const range = mesh.face_ranges.find((candidate) => candidate.face_index === faceIndex);
  if (!range || range.tri_count === 0) return null;
  if (solidIndices && (range.solid_index == null || !solidIndices.includes(range.solid_index))) return null;
  const bounds = meshBounds(mesh, solidIndices);
  if (!bounds) return null;

  let area = 0;
  const weightedCenter: [number, number, number] = [0, 0, 0];
  const weightedNormal: [number, number, number] = [0, 0, 0];
  const triangleNormals: [number, number, number][] = [];

  for (let triangle = range.tri_start; triangle < range.tri_start + range.tri_count; triangle += 1) {
    const ia = mesh.indices[triangle * 3] * 3;
    const ib = mesh.indices[triangle * 3 + 1] * 3;
    const ic = mesh.indices[triangle * 3 + 2] * 3;
    const a: [number, number, number] = [mesh.positions[ia], mesh.positions[ia + 1], mesh.positions[ia + 2]];
    const b: [number, number, number] = [mesh.positions[ib], mesh.positions[ib + 1], mesh.positions[ib + 2]];
    const c: [number, number, number] = [mesh.positions[ic], mesh.positions[ic + 1], mesh.positions[ic + 2]];
    const ab: [number, number, number] = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const ac: [number, number, number] = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const cross: [number, number, number] = [
      ab[1] * ac[2] - ab[2] * ac[1],
      ab[2] * ac[0] - ab[0] * ac[2],
      ab[0] * ac[1] - ab[1] * ac[0],
    ];
    const triangleArea = Math.hypot(cross[0], cross[1], cross[2]) / 2;
    if (triangleArea <= 1e-12) continue;
    const triangleNormal = normalize(cross);
    triangleNormals.push(triangleNormal);
    area += triangleArea;
    for (let axis = 0; axis < 3; axis += 1) {
      weightedCenter[axis] += ((a[axis] + b[axis] + c[axis]) / 3) * triangleArea;
      weightedNormal[axis] += triangleNormal[axis] * triangleArea;
    }
  }
  if (area <= 1e-12 || triangleNormals.length === 0) return null;

  const center: [number, number, number] = [
    weightedCenter[0] / area,
    weightedCenter[1] / area,
    weightedCenter[2] / area,
  ];
  const averagedNormal = normalize(weightedNormal);
  const planar = triangleNormals.every((normal) =>
    Math.abs(
      normal[0] * averagedNormal[0] +
      normal[1] * averagedNormal[1] +
      normal[2] * averagedNormal[2],
    ) >= 0.999,
  );
  const dominant = Math.max(...averagedNormal.map(Math.abs));
  const dominantIndex = averagedNormal.map(Math.abs).indexOf(dominant) as 0 | 1 | 2;
  const axis: FaceAxis | null = planar && dominant >= 0.98
    ? (["x", "y", "z"] as const)[dominantIndex]
    : null;

  const side: -1 | 1 = axis
    ? (averagedNormal[AXIS_INDEX[axis]] >= 0 ? 1 : -1)
    : 1;
  const normal: [number, number, number] = axis
    ? [axis === "x" ? side : 0, axis === "y" ? side : 0, axis === "z" ? side : 0]
    : averagedNormal;
  const axisIndex = axis == null ? null : AXIS_INDEX[axis];
  const span = axisIndex == null ? 0 : bounds.max[axisIndex] - bounds.min[axisIndex];
  const boundary = axisIndex == null
    ? 0
    : side > 0 ? bounds.max[axisIndex] : bounds.min[axisIndex];
  const atBoundary = axisIndex != null && Math.abs(center[axisIndex] - boundary) <= Math.max(0.05, span * 1e-3);

  return { faceIndex, area, center, normal, axis, side, planar, atBoundary, axisSpan: span };
}

export function resolveFaceFeatureTarget(
  mesh: MeshData,
  faceIndex: number,
  partId: string,
  solidIndices?: number[],
): FaceFeatureTarget | null {
  const face = analyzeFace(mesh, faceIndex, solidIndices);
  if (!face?.planar || !face.axis || !face.atBoundary) return null;

  const bounds = meshBounds(mesh, solidIndices);
  if (!bounds) return null;
  const axes: Record<FaceAxis, [FaceAxis, FaceAxis]> = {
    x: ["y", "z"],
    y: ["x", "z"],
    z: ["x", "y"],
  };
  const [uAxis, vAxis] = axes[face.axis];
  const uIndex = AXIS_INDEX[uAxis];
  const vIndex = AXIS_INDEX[vAxis];
  const boundsCenter = (axis: 0 | 1 | 2) => (bounds.min[axis] + bounds.max[axis]) / 2;

  return {
    ...face,
    partId,
    uAxis,
    vAxis,
    uLabel: uAxis.toUpperCase(),
    vLabel: vAxis.toUpperCase(),
    anchor: [
      face.center[uIndex] - boundsCenter(uIndex),
      face.center[vIndex] - boundsCenter(vIndex),
    ],
  };
}

export function resolveSheetBendTarget(
  mesh: MeshData,
  faceIndex: number,
  partId: string,
  solidIndices?: number[],
): FaceFeatureTarget | null {
  const face = analyzeFace(mesh, faceIndex, solidIndices);
  if (!face?.planar || !face.axis || !face.atBoundary) return null;
  if (face.axis === "z" && face.side !== 1) return null;

  const bounds = meshBounds(mesh, solidIndices);
  if (!bounds) return null;
  const boundsCenter = (axis: 0 | 1 | 2) => (bounds.min[axis] + bounds.max[axis]) / 2;
  const axes: Record<FaceAxis, [FaceAxis, FaceAxis]> = {
    x: ["y", "z"],
    y: ["x", "z"],
    z: ["x", "y"],
  };
  const [uAxis, vAxis] = axes[face.axis];
  return {
    ...face,
    partId,
    uAxis,
    vAxis,
    uLabel: uAxis.toUpperCase(),
    vLabel: vAxis.toUpperCase(),
    anchor: [
      face.center[AXIS_INDEX[uAxis]] - boundsCenter(AXIS_INDEX[uAxis]),
      face.center[AXIS_INDEX[vAxis]] - boundsCenter(AXIS_INDEX[vAxis]),
    ],
  };
}

export function faceFeatureArgs(
  target: FaceFeatureTarget,
  mode: "add" | "cut",
  profile: FaceFeatureProfile,
  depth: number | "through",
): FaceFeatureArgs {
  return {
    target_id: target.partId,
    mode,
    face_ref: {
      kind: "outer_planar",
      axis: target.axis!,
      side: target.side,
      anchor: target.anchor,
      selected_area: target.area,
    },
    profile,
    depth,
  };
}

export function faceDomeArgs(
  target: FaceFeatureTarget,
  mode: "add" | "cut",
  center: [number, number],
  diameter: number,
  height: number,
): FaceDomeArgs {
  return {
    target_id: target.partId,
    mode,
    face_ref: {
      kind: "outer_planar",
      axis: target.axis!,
      side: target.side,
      anchor: target.anchor,
      selected_area: target.area,
    },
    center,
    diameter,
    height,
  };
}

export function sheetBendArgs(
  target: FaceFeatureTarget,
  bendAxis: "x" | "y",
  position: number,
  angle: number,
  insideRadius: number,
  movingSide: -1 | 1,
  direction: -1 | 1,
): SheetBendArgs {
  return {
    target_id: target.partId,
    face_ref: {
      kind: "outer_planar",
      axis: target.axis!,
      side: target.side,
      anchor: target.anchor,
      selected_area: target.area,
    },
    bend_axis: bendAxis,
    position,
    angle,
    inside_radius: insideRadius,
    moving_side: movingSide,
    direction,
  };
}

function parameterValue(part: PartDef, template: TemplateDef, name: string): number | null {
  const direct = part.params[name];
  if (Number.isFinite(direct)) return direct;
  const definition = template.params.find((parameter) => parameter.name === name);
  return definition && Number.isFinite(definition.default) ? definition.default : null;
}

function minimumFor(part: PartDef, parameter: string): number {
  if (part.template === "plate_with_holes" && (parameter === "length" || parameter === "width")) {
    return 2 * (part.params.hole_offset ?? 10) + 0.1;
  }
  if (part.template === "case_with_lid" && (parameter === "length" || parameter === "width")) {
    return 2 * (part.params.wall ?? 2) + 2 * (part.params.gap ?? 0.2) + 2 * (part.params.lip_wall ?? 2) + 0.1;
  }
  return 0.1;
}

export function resolveFaceEditTarget(
  mesh: MeshData,
  faceIndex: number,
  part: PartDef,
  template: TemplateDef,
  solidIndices?: number[],
): FaceEditTarget | null {
  const face = analyzeFace(mesh, faceIndex, solidIndices);
  if (!face?.planar || !face.axis || !face.atBoundary) return null;

  let parameter: string | null = null;
  let label = "";
  let deltaFactor = 1;
  let symmetric = false;

  if (part.template === "box") {
    if (face.axis === "x") [parameter, label, deltaFactor, symmetric] = ["length", "Длина", 2, true];
    if (face.axis === "y") [parameter, label, deltaFactor, symmetric] = ["width", "Ширина", 2, true];
    if (face.axis === "z" && face.side > 0) [parameter, label] = ["height", "Высота"];
  } else if (part.template === "cylinder") {
    if (face.axis === "z" && face.side > 0) [parameter, label] = ["height", "Высота"];
  } else if (part.template === "plate_with_holes") {
    if (face.axis === "x") [parameter, label, deltaFactor, symmetric] = ["length", "Длина", 2, true];
    if (face.axis === "y") [parameter, label, deltaFactor, symmetric] = ["width", "Ширина", 2, true];
    if (face.axis === "z" && face.side > 0) [parameter, label] = ["height", "Высота"];
  } else if (part.template === "washer") {
    if (face.axis === "z" && face.side > 0) [parameter, label] = ["height", "Высота"];
  } else if (part.template === "bracket_l") {
    if (face.side > 0 && face.axis === "x") [parameter, label] = ["a_length", "Длина"];
    if (face.side > 0 && face.axis === "y") [parameter, label] = ["a_width", "Ширина основания"];
    if (face.side > 0 && face.axis === "z") [parameter, label] = ["b_height", "Высота стойки"];
  } else if (part.template === "case_with_lid") {
    if (face.axis === "x") [parameter, label, deltaFactor, symmetric] = ["length", "Длина", 2, true];
    if (face.axis === "y") [parameter, label, deltaFactor, symmetric] = ["width", "Ширина", 2, true];
    if (face.axis === "z" && face.side > 0) [parameter, label] = ["lid_thickness", "Толщина крышки"];
  }

  if (!parameter) return null;
  const current = parameterValue(part, template, parameter);
  if (current == null) return null;
  const parameterDefinition = template.params.find((candidate) => candidate.name === parameter);
  return {
    ...face,
    partId: part.part_id,
    mode: "parameter",
    parameter,
    label: parameterDefinition?.label ?? label,
    current,
    minimum: Math.max(minimumFor(part, parameter), parameterDefinition?.min ?? 0.1),
    deltaFactor,
    symmetric,
  };
}

export function resolveGenericFaceEditTarget(
  mesh: MeshData,
  faceIndex: number,
  partId: string,
  solidIndices?: number[],
): FaceEditTarget | null {
  const range = mesh.face_ranges.find((candidate) => candidate.face_index === faceIndex);
  const faceRef = range?.face_ref;
  if (!faceRef || faceRef.kind !== "planar") return null;
  const face = analyzeFace(mesh, faceIndex, solidIndices);
  if (!face?.planar) return null;
  return {
    ...face,
    partId,
    mode: "offset",
    faceRef,
    center: faceRef.center,
    normal: normalize(faceRef.normal),
    area: faceRef.area,
    parameter: "",
    label: "Смещение грани",
    current: 0,
    minimum: -Infinity,
    deltaFactor: 1,
    symmetric: false,
  };
}

export function pushPullValue(target: FaceEditTarget, delta: number): number {
  const raw = Math.max(target.minimum, target.current + delta * target.deltaFactor);
  return Math.round(raw * 10) / 10;
}

export function pushPullDelta(target: FaceEditTarget, value: number): number {
  return (value - target.current) / target.deltaFactor;
}
