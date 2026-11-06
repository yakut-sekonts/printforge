export type Size3 = [number, number, number];
export type ResizeCorner = [-1 | 1, -1 | 1, -1 | 1];
export interface ResizeHandle {
  corner: ResizeCorner;
  axis: 0 | 1 | 2 | null;
}
export interface BodyResize {
  target_id: string;
  size: Size3;
  anchor: ResizeCorner;
}

export function resizeDirection(size: Size3, handle: ResizeHandle): Size3 {
  const largest = Math.max(...size);
  return size.map((value, axis) => handle.axis == null
    ? handle.corner[axis] * value / largest
    : axis === handle.axis ? handle.corner[axis] : 0) as Size3;
}

export function resizedDimensions(size: Size3, handle: ResizeHandle, delta: number, fine = false): Size3 {
  if (!size.every((value) => Number.isFinite(value) && value > 0) || !Number.isFinite(delta)) {
    throw new Error("Размеры должны быть положительными, смещение — конечным числом.");
  }
  const step = fine ? 0.1 : 1;
  const snapped = Math.sign(delta) * Math.round(Math.abs(delta) / step) * step;
  if (snapped === 0) return [...size];
  if (handle.axis != null) {
    return size.map((value, axis) => axis === handle.axis ? Math.max(Math.min(0.1, value), value + snapped) : value) as Size3;
  }
  const largest = Math.max(...size);
  const factor = Math.max(Math.min(1, 0.1 / Math.min(...size)), (largest + snapped) / largest);
  return size.map((value) => value * factor) as Size3;
}

export function resizeAnchor(handle: ResizeHandle): ResizeCorner {
  return handle.corner.map((side) => -side) as ResizeCorner;
}

export function resizeChanged(before: Size3, after: Size3): boolean {
  return before.some((value, axis) => Math.abs(value - after[axis]) > 1e-7);
}

export function sizeLabel(size: Size3): string {
  return size.map((value) => String(Math.round(value * 100) / 100)).join(" × ") + " мм";
}
