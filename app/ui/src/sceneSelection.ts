import type { EdgeRef, MeshData, PartStats } from "./types";

export function partIdForSolid(parts: Pick<PartStats, "part_id" | "solid_count">[], solidIndex: number): string | null {
  let firstSolid = 0;
  for (const part of parts) {
    if (solidIndex >= firstSolid && solidIndex < firstSolid + part.solid_count) return part.part_id;
    firstSolid += part.solid_count;
  }
  return null;
}

export function solidIndicesForParts(parts: Pick<PartStats, "part_id" | "solid_count">[], partIds: string[]): number[] {
  const selected = new Set(partIds);
  const indices: number[] = [];
  let firstSolid = 0;
  for (const part of parts) {
    if (selected.has(part.part_id)) {
      for (let index = 0; index < part.solid_count; index += 1) indices.push(firstSolid + index);
    }
    firstSolid += part.solid_count;
  }
  return indices;
}

export function togglePartSelection(current: string[], partId: string, additive: boolean): string[] {
  if (!additive) return [partId];
  return current.includes(partId) ? current.filter((candidate) => candidate !== partId) : [...current, partId];
}

export function parseMillimeters(raw: string): number | null {
  const normalized = raw.trim().replace(",", ".");
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(normalized)) return null;
  const value = Number(normalized);
  return Number.isFinite(value) ? value : null;
}

export function edgePoints(edge: EdgeRef): Array<[number, number, number]> {
  if (edge.points && edge.points.length >= 2) return edge.points;
  return edge.p0 && edge.p1 ? [edge.p0, edge.p1] : [];
}

export function selectedBoundsCenter(mesh: MeshData | null, solidIndices: number[]): [number, number, number] {
  const minimum = [Infinity, Infinity, Infinity];
  const maximum = [-Infinity, -Infinity, -Infinity];
  if (mesh) for (const range of mesh.face_ranges) {
    if (range.solid_index == null || !solidIndices.includes(range.solid_index)) continue;
    for (let index = range.tri_start * 3; index < (range.tri_start + range.tri_count) * 3; index += 1) {
      const vertex = mesh.indices[index] * 3;
      for (let axis = 0; axis < 3; axis += 1) {
        minimum[axis] = Math.min(minimum[axis], mesh.positions[vertex + axis]);
        maximum[axis] = Math.max(maximum[axis], mesh.positions[vertex + axis]);
      }
    }
  }
  return minimum.map((value, axis) => Number.isFinite(value) ? (value + maximum[axis]) / 2 : 0) as [number, number, number];
}
