import type {
  AiConnectionTest, AiOperation, AiPlanResponse, AiProviderConfig, AiProviderInfo,
  DocState, EdgeRef, ExportResult, FaceDomeArgs, FaceFeatureArgs, GeoError, ImportResult, MeshData,
  PrintCheckResult, SheetBendArgs,
} from "./types";

const HOME = "/Users/semenkontsevoy";

export function expandTilde(path: string): string {
  if (path === "~") return HOME;
  if (path.startsWith("~/")) return HOME + path.slice(1);
  return path;
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI__" in window;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (!signal?.aborted) return;
  throw signal.reason instanceof Error
    ? signal.reason
    : new DOMException("Операция отменена", "AbortError");
}

async function call<T>(command: string, args?: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  throwIfAborted(signal);
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    try {
      const result = (await invoke<T>(command, args)) as T;
      throwIfAborted(signal);
      return result;
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      throw parseIpcError(e);
    }
  }
  const resp = await fetch(`http://localhost:8787/api/${command}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args ?? {}),
    signal,
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
  if (e && typeof e === "object") {
    const parsed = e as Partial<GeoError>;
    if (parsed.code || parsed.message) {
      return {
        code: parsed.code ?? "error",
        message: parsed.message ?? "Неизвестная ошибка",
        detail: parsed.detail,
      };
    }
  }
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
  docFaceFeature: (args: FaceFeatureArgs) =>
    call<DocState>("doc_face_feature", args as unknown as Record<string, unknown>),
  docFaceDome: (args: FaceDomeArgs) =>
    call<DocState>("doc_face_dome", args as unknown as Record<string, unknown>),
  docSheetBend: (args: SheetBendArgs) =>
    call<DocState>("doc_sheet_bend", args as unknown as Record<string, unknown>),
  docArrayCircular: (partId: string, count: number, angle?: number, center?: [number, number, number]) =>
    call<DocState>("doc_array_circular", { part_id: partId, count, angle, center }),
  docAlign: (partId: string, axis: "x" | "y" | "z", align: "center" | "min" | "max", value: number) =>
    call<DocState>("doc_align", { part_id: partId, axis, align, value }),
  measure: (args: { type: "bbox" | "volume" | "face_diameter" | "distance"; face_index?: number; p0?: [number, number, number]; p1?: [number, number, number] }) =>
    call<Record<string, unknown>>(`measure`, args as Record<string, unknown>),
  aiProviders: () => call<AiProviderInfo>("ai_providers"),
  aiConfigure: (config: AiProviderConfig) => call<AiProviderInfo>(
    "ai_configure",
    isTauri()
      ? {
          provider: config.provider,
          baseUrl: config.base_url,
          model: config.model,
          apiKey: config.api_key,
          clearApiKey: config.clear_api_key,
        }
      : config as unknown as Record<string, unknown>,
  ),
  aiTestConnection: () => call<AiConnectionTest>("ai_test_connection"),
  aiPlan: (text: string, signal?: AbortSignal) =>
    call<AiPlanResponse>("ai_plan", { text }, signal),
  docTransaction: (args: {
    operations: AiOperation[];
    base_revision: number;
    document_instance_id: string | number;
    plan_hash: string;
    action_id?: string;
    mode: "apply" | "preview";
  }) =>
    call<DocState>("doc_transaction", args as unknown as Record<string, unknown>),
  docFillet: (edge_ref: EdgeRef, radius: number, partId?: string) =>
    call<DocState>("doc_fillet", { edge_ref, radius, part_id: partId }),
  docChamfer: (edge_ref: EdgeRef, distance: number, partId?: string) =>
    call<DocState>("doc_chamfer", { edge_ref, distance, part_id: partId }),
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
