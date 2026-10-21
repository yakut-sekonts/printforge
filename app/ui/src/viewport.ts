import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { MeshData, FaceRange, EdgeRef } from "./types";

export type ViewName = "top" | "front" | "side" | "iso";

export interface ViewportEvents {
  onHoverFace: (face: number | null) => void;
  onSelectFace: (face: number | null) => void;
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

function subGeometry(geo: THREE.BufferGeometry, range: FaceRange): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", geo.getAttribute("position"));
  const idx = geo.getIndex()!;
  const arr = idx.array.slice(range.tri_start * 3, (range.tri_start + range.tri_count) * 3);
  g.setIndex(new THREE.BufferAttribute(arr, 1));
  return g;
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
  private hoverOverlay: THREE.Object3D | null = null;
  private selOverlay: THREE.Object3D | null = null;
  private edgeMarker: THREE.Group | null = null;
  private dimGroup: THREE.Group | null = null;
  private resizeObs!: ResizeObserver;
  private downPos = { x: 0, y: 0 };
  private orthoMode = false;
  private halfSize = 100;

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
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.PAN,
    };
    this.controls.addEventListener("change", () => this.render());

    let lastInteraction = "";
    const wheelHandler = () => this.events.onCameraZoomed();
    this.renderer.domElement.addEventListener("wheel", wheelHandler, { passive: true });
    this.controls.addEventListener("start", () => {
      lastInteraction = "rotate";
    });
    this.controls.addEventListener("end", () => {
      if (lastInteraction === "rotate") this.events.onCameraRotated();
      lastInteraction = "";
    });

    this.renderer.domElement.addEventListener("pointermove", (e) => this.onPointerMove(e));
    this.renderer.domElement.addEventListener("pointerdown", (e) => {
      this.downPos = { x: e.clientX, y: e.clientY };
    });
    this.renderer.domElement.addEventListener("pointerup", (e) => {
      if (e.button !== 0) return;
      const dx = e.clientX - this.downPos.x;
      const dy = e.clientY - this.downPos.y;
      if (dx * dx + dy * dy < 25) this.onClick(e);
    });
    this.renderer.domElement.addEventListener("contextmenu", (e) => e.preventDefault());

    this.resizeObs = new ResizeObserver(() => this.onResize());
    this.resizeObs.observe(this.container);
    this.animate();
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

  private animate = () => {
    requestAnimationFrame(this.animate);
    if (this.controls.enableDamping) this.controls.update();
    this.render();
  };

  private render() {
    this.renderer.render(this.scene, this.camera);
  }

  private pickFace(e: PointerEvent): number | null {
    if (!this.mesh) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObject(this.mesh, false);
    if (!hits.length || hits[0].faceIndex == null) return null;
    const tri = hits[0].faceIndex;
    const range = this.faceRanges.find((r) => tri >= r.tri_start && tri < r.tri_start + r.tri_count);
    return range ? range.face_index : null;
  }

  private onPointerMove(e: PointerEvent) {
    const face = this.pickFace(e);
    this.setHoverFace(face);
    this.events.onHoverFace(face);
  }

  private onClick(e: PointerEvent) {
    const face = this.pickFace(e);
    this.events.onSelectFace(face);
  }

  setHoverFace(face: number | null) {
    if (this.hoverOverlay) {
      this.scene.remove(this.hoverOverlay);
      this.hoverOverlay = null;
    }
    if (face == null || !this.mesh) return;
    const range = this.faceRanges.find((r) => r.face_index === face);
    if (!range) return;
    const sub = subGeometry(this.mesh.geometry as THREE.BufferGeometry, range);
    const edges = new THREE.EdgesGeometry(sub, 1);
    this.hoverOverlay = new THREE.LineSegments(
      edges, new THREE.LineBasicMaterial({ color: COLOR.hover })
    );
    this.scene.add(this.hoverOverlay);
  }

  // Подсветка выбранного ребра для op.fillet: маркер-крест в середине ребра
  // (edge_ref отдаёт только kind/length/midpoint, направление ребра неизвестно)
  setEdgeMarker(edge: EdgeRef | null) {
    if (this.edgeMarker) {
      this.scene.remove(this.edgeMarker);
      this.edgeMarker = null;
    }
    if (!edge) return;
    const [x, y, z] = docToThree(...edge.midpoint);
    const group = new THREE.Group();
    const mat = new THREE.LineBasicMaterial({ color: COLOR.selEdge });
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
    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(1.2, 12, 12),
      new THREE.MeshBasicMaterial({ color: COLOR.selEdge })
    );
    dot.position.set(x, y, z);
    dot.renderOrder = 18;
    group.add(dot);
    this.edgeMarker = group;
    this.scene.add(group);
  }

  setSelectedFace(face: number | null) {
    if (this.selOverlay) {
      this.scene.remove(this.selOverlay);
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

  setMesh(data: MeshData | null) {
    if (this.mesh) {
      this.scene.remove(this.mesh);
      this.mesh.geometry.dispose();
      this.mesh = null;
    }
    this.setHoverFace(null);
    this.setSelectedFace(null);
    this.faceRanges = data?.face_ranges ?? [];
    if (!data) {
      this.rebuildDimensions(null);
      return;
    }
    const pos = new Float32Array(data.positions.length);
    for (let i = 0; i < data.positions.length; i += 3) {
      const [x, y, z] = docToThree(data.positions[i], data.positions[i + 1], data.positions[i + 2]);
      pos[i] = x; pos[i + 1] = y; pos[i + 2] = z;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setIndex(data.indices);
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
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
    this.controls.target.copy(target);
    this.controls.addEventListener("change", () => this.render());
    this.render();
    return this.orthoMode;
  }

  dispose() {
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
