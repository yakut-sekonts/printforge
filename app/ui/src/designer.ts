import type { DocStats, MeshResource, Operation, Point3, EdgeRef } from "./types";

export type DesignerAction =
  | { type: "append"; operation: Record<string, unknown> }
  | { type: "edit"; index: number; changes: Record<string, unknown> }
  | { type: "convert_mesh" };

export interface DesignerPreview {
  stats: DocStats;
  mesh: MeshResource;
  base_revision: number;
  document_instance_id: string | number;
}

export function edgeDesignerAction(kind: "fillet" | "chamfer", edge: EdgeRef, size: number, partId: string): DesignerAction {
  return { type: "append", operation: { op: kind, part_id: partId, edge_ref: edge,
    [kind === "fillet" ? "radius" : "distance"]: size } };
}

const NAMES: Record<string, string> = {
  fillet: "Скругление", chamfer: "Фаска", face_offset: "Смещение грани", face_shell: "Оболочка",
  face_feature: "Элемент на грани", face_dome: "Купол", resize_body: "Масштабирование",
  mate: "Сборочная связь",
  resize_parametric: "Габариты с сохранением элементов", transform: "Положение",
  mesh_source: "Исходная сетка", step_source: "Исходный STEP", image_relief_source: "Рельеф",
  mesh_deform: "Мягкая деформация", boolean: "Булева операция", split: "Разделение",
  array_linear: "Линейный массив", array_circular: "Круговой массив", mirror: "Отражение",
  sketch_extrude: "Выдавливание эскиза", profile_extrude: "Выдавливание профиля",
  sheet_bend: "Изгиб", revolve: "Вращение профиля", sweep: "По траектории", loft: "По сечениям",
  mesh_transform: "Положение сетки", mesh_repair: "Исправление сетки", mesh_decimate: "Упрощение сетки",
  constrained_sketch_extrude: "Выдавливание эскиза с ограничениями", shell: "Оболочка",
  draft_prism: "Уклон", rib: "Ребро жёсткости", fit_pocket: "Посадочный карман",
  vector_extrude: "Выдавливание SVG/DXF", text_relief: "Текстовый рельеф",
  thread_pair: "Резьбовая пара", clearance_calibration: "Калибровка зазоров", split_connector_pair: "Разделение со штифтами",
};

export function operationName(operation: Operation): string {
  const size = operation.radius ?? operation.distance;
  return `${NAMES[operation.op] ?? operation.op}${size == null ? "" : ` · ${size} мм`}`;
}

export const EDIT_FIELDS: Record<string, string[]> = {
  fillet: ["radius"], chamfer: ["distance"], face_offset: ["distance"], face_shell: ["thickness"],
  face_feature: ["profile", "depth", "mode", "dimension_bindings"], face_dome: ["diameter", "height", "mode"],
  mate: ["gap"], constrained_sketch_extrude: ["sketch", "depth", "mode"],
  resize_body: ["size", "anchor"], resize_parametric: ["size", "anchor"],
  transform: ["translate", "rotate_deg", "pivot"], mesh_deform: ["center", "delta", "radius"],
  mesh_transform: ["translate", "rotate_deg", "pivot", "scale"],
  array_linear: ["count", "step"], array_circular: ["count", "angle", "center"],
  mirror: ["plane"], split: ["plane", "offset"],
  sheet_bend: ["position", "angle", "inside_radius", "moving_side", "direction"],
};

export function editableParameters(operation: Operation): Record<string, unknown> {
  const source = operation as unknown as Record<string, unknown>;
  return Object.fromEntries((EDIT_FIELDS[operation.op] ?? []).filter((key) => source[key] != null)
    .map((key) => [key, source[key]]));
}

export function constrainedSize(size: Point3, axis: number, value: number, constraint?: string): Point3 {
  if (!Number.isFinite(value) || value <= 0) throw new Error("Размер должен быть больше нуля.");
  return size.map((current, index) => index === axis || constraint === "uniform" ||
    (constraint === "radial" && axis < 2 && index < 2) ? value : current) as Point3;
}

export function snapTranslation(bounds: number[], others: number[][], axis: number, delta: number,
  grid: number, tolerance: number): { delta: number; label: string; target?: number } {
  const step = Number.isFinite(grid) && grid > 0 ? grid : 1;
  let best: { delta: number; label: string; target?: number } = { delta: Math.round(delta / step) * step, label: `Сетка ${step} мм` };
  let distance = tolerance;
  const landmarks = (box: number[]) => [box[axis], (box[axis] + box[axis + 3]) / 2, box[axis + 3]];
  for (const box of others) {
    for (const target of landmarks(box)) {
      for (const source of landmarks(bounds)) {
        const candidate = target - source;
        const error = Math.abs(candidate - delta);
        if (error < distance) {
          distance = error;
          best = { delta: candidate, label: `Привязка ${"XYZ"[axis]}: ${target.toFixed(2)} мм`, target };
        }
      }
    }
  }
  return best;
}

export function deformPositions(positions: ArrayLike<number>, center: Point3, delta: Point3, radius: number): Float32Array {
  const result = Float32Array.from(positions);
  if (!Number.isFinite(radius) || radius <= 0) throw new Error("Радиус кисти должен быть больше нуля.");
  for (let offset = 0; offset < result.length; offset += 3) {
    const squared = center.reduce((sum, value, axis) => sum + (positions[offset + axis] - value) ** 2, 0);
    const weight = Math.max(0, 1 - squared / radius ** 2) ** 2;
    for (let axis = 0; axis < 3; axis += 1) result[offset + axis] += delta[axis] * weight;
  }
  return result;
}

export class PreviewQueue {
  private token = 0;
  private pending: Promise<void> = Promise.resolve();
  invalidate(): void { this.token += 1; }
  drain(): Promise<void> { return this.pending; }
  schedule<T>(request: () => Promise<T>, accept: (value: T) => void, reject: (cause: unknown) => void): void {
    const token = ++this.token;
    this.pending = this.pending.then(async () => {
      if (token !== this.token) return;
      try {
        const value = await request();
        if (token === this.token) accept(value);
      } catch (cause) { if (token === this.token) reject(cause); }
    });
  }
}
