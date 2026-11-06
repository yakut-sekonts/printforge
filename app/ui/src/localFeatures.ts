import type { FaceFeatureProfile } from "./types";
import type { DesignerAction } from "./designer";

export function localFeatureValue(changes: Record<string, unknown>, field: string): number {
  const profile = changes.profile as FaceFeatureProfile | undefined;
  if (["diameter", "width", "height"].includes(field)) return Number((profile as unknown as Record<string, unknown>)?.[field] ?? 1);
  if (field === "u" || field === "v") return profile?.center?.[field === "u" ? 0 : 1] ?? 0;
  return typeof changes[field] === "number" ? changes[field] as number : 1;
}

export function changeLocalFeature(changes: Record<string, unknown>, field: string, value: number): Record<string, unknown> {
  if (!Number.isFinite(value)) throw new Error("Размер должен быть конечным числом.");
  if (["diameter", "width", "height", "u", "v"].includes(field)) {
    const profile = { ...(changes.profile as FaceFeatureProfile) };
    if (field === "diameter" || field === "width" || field === "height") profile[field] = Math.max(0.1, value);
    else profile.center = (profile.center ?? [0, 0]).map((old, axis) => axis === (field === "u" ? 0 : 1) ? value : old) as [number, number];
    return { ...changes, profile };
  }
  return { ...changes, [field]: Math.max(0.1, value) };
}

export function localHandleEnabled(changes: Record<string, unknown>, field: string): boolean {
  const bindings = changes.dimension_bindings as Record<string, unknown> | undefined;
  if (field === "depth" && changes.depth === "through") return false;
  return !(bindings && (field === "diameter" ? bindings.equal_diameter != null : (field === "u" || field === "v") && bindings[field] != null));
}

export async function findSmallerFeature(action: DesignerAction, field: "radius" | "distance", start: number,
  validate: (candidate: DesignerAction) => Promise<void>, cancelled: () => boolean): Promise<number | null> {
  if (!Number.isFinite(start) || start <= 0) return null;
  for (let attempt = 1; attempt <= 6; attempt += 1) {
    const value = Math.floor(start / 2 ** attempt * 100) / 100;
    if (cancelled() || value < 0.01) return null;
    const candidate = structuredClone(action);
    if (candidate.type === "append") candidate.operation[field] = value;
    else if (candidate.type === "edit") candidate.changes[field] = value;
    else return null;
    try { await validate(candidate); return cancelled() ? null : value; }
    catch (cause) {
      const code = cause && typeof cause === "object" && "code" in cause ? cause.code : null;
      if (code !== "fillet_failed" && code !== "chamfer_failed") throw cause;
    }
  }
  return null;
}
