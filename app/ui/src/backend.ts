import type { DocState, MeshData, ExportResult, ImportResult, PrintCheckResult, EdgeRef, GeoError } from "./types";

const HOME = "/Users/semenkontsevoy";

export function expandTilde(path: string): string {
  if (path === "~") return HOME;
  if (path.startsWith("~/")) return HOME + path.slice(1);
  return path;
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI__" in window;
}

async function call<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    try {
      return (await invoke<T>(command, args)) as T;
    } catch (e) {
      throw parseIpcError(e);
    }
  }
  const resp = await fetch(`http://localhost:8787/api/${command}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args ?? {}),
  });
  const text = await resp.text();
  let data: unknown;
  try { data = JSON.parse(text); } catch { data = text; }
  const errVal = data && typeof data === "object" ? (data as Record<string, unknown>).error : null;
  // DocState.error — часть контракта (DOC-005), не транспортная ошибка;
  // бросаем только HTTP-сбой или строковую ошибку shim'а
  if (!resp.ok || typeof errVal === "string") {
    throw parseIpcError(errVal ?? `HTTP ${resp.status}`);
  }
  return data as T;
}

export function parseIpcError(e: unknown): GeoError {
  const raw = typeof e === "string" ? e : e instanceof Error ? e.message : String(e);
  try {
    const parsed = JSON.parse(raw) as Partial<GeoError>;
    if (parsed && typeof parsed === "object" && (parsed.code || parsed.message)) {
      return {
        code: parsed.code ?? "error",
        message: parsed.message ?? raw,
        detail: parsed.detail,
      };
    }
  } catch { /* не JSON */ }
  return { code: "error", message: raw };
}

export const backend = {
  docCreate: (template: string, params?: Record<string, number>) =>
    call<DocState>("doc_create", { template, params }),
  docAddPart: (template: string, params?: Record<string, number>) =>
    call<DocState>("doc_add_part", { template, params }),
  docSetParameter: (name: string, value: number, expression?: string, partId?: string) =>
    call<DocState>("doc_set_parameter", { name, value, expression, part_id: partId }),
  docBoolean: (kind: "union" | "subtract" | "intersect", targetId: string, toolId: string, keepTool?: boolean) =>
    call<DocState>("doc_boolean", { boolean: kind, target_id: targetId, tool_id: toolId, keep_tool: keepTool }),
  docArray: (partId: string, count: number, step: [number, number, number]) =>
    call<DocState>("doc_array", { part_id: partId, count, step }),
  docMirror: (partId: string, plane: "XY" | "XZ" | "YZ") =>
    call<DocState>("doc_mirror", { part_id: partId, plane }),
  docSplit: (partId: string, plane: "XY" | "XZ" | "YZ", offset: number) =>
    call<DocState>("doc_split", { part_id: partId, plane, offset }),
  docTransform: (partId: string, translate: [number, number, number]) =>
    call<DocState>("doc_transform", { part_id: partId, translate }),
  docProfileExtrude: (args: {
    mode: "add" | "cut";
    plane: "XY" | "XZ" | "YZ";
    profile: Record<string, unknown>;
    depth?: number | "through";
    target_id?: string;
  }) => call<DocState>("doc_profile_extrude", args as Record<string, unknown>),
  docArrayCircular: (partId: string, count: number, angle?: number, center?: [number, number, number]) =>
    call<DocState>("doc_array_circular", { part_id: partId, count, angle, center }),
  docAlign: (partId: string, axis: "x" | "y" | "z", align: "center" | "min" | "max", value: number) =>
    call<DocState>("doc_align", { part_id: partId, axis, align, value }),
  measure: (args: { type: "bbox" | "volume" | "face_diameter" | "distance"; face_index?: number; p0?: [number, number, number]; p1?: [number, number, number] }) =>
    call<Record<string, unknown>>(`measure`, args as Record<string, unknown>),
  docFillet: (edge_ref: EdgeRef, radius: number, partId?: string) =>
    call<DocState>("doc_fillet", { edge_ref, radius, part_id: partId }),
  docClearError: () => call<DocState>("doc_clear_error"),
  docUndo: () => call<DocState>("doc_undo"),
  docRedo: () => call<DocState>("doc_redo"),
  docGetState: () => call<DocState>("doc_get_state"),
  docGetMesh: () => call<MeshData>("doc_get_mesh"),
  docGetImportedMesh: (path: string) => call<MeshData>("doc_get_imported_mesh", { path }),
  docSave: (path: string) => call<DocState>("doc_save", { path }),
  docOpen: (path: string) => call<DocState>("doc_open", { path }),
  docExport: (path: string, format: "stl" | "step" | "3mf", linearDeflection?: number) =>
    call<ExportResult>("doc_export", { path, format, linear_deflection: linearDeflection }),
  docImport: (path: string, format: "step" | "stl", unitScale?: number) =>
    call<ImportResult>("doc_import", { path, format, unit_scale: unitScale }),
  printCheck: (printer: { x: number; y: number; z: number }) =>
    call<PrintCheckResult>("print_check", { printer }),
  // совместимость M1
  docCreatePlate: (p: { length: number; width: number; height: number; hole_diameter: number; hole_offset: number }) =>
    call<DocState>("doc_create_plate", p),
  docExportStl: (path: string, linearDeflection?: number) =>
    call<ExportResult>("doc_export_stl", { path, linear_deflection: linearDeflection }),
  docNewTutorial: () => call<DocState>("doc_new_tutorial"),
  docSwitchSlot: (slot: "main" | "tutorial") => call<DocState>("doc_switch_slot", { slot }),
};
