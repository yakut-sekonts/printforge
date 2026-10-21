import type { DocState, MeshData, ExportResult, GeoError } from "./types";

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
  if (!resp.ok || errVal) {
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
  docCreatePlate: (p: { length: number; width: number; height: number; hole_diameter: number; hole_offset: number }) =>
    call<DocState>("doc_create_plate", p),
  docSetParameter: (name: string, value: number, expression?: string) =>
    call<DocState>("doc_set_parameter", { name, value, expression }),
  docUndo: () => call<DocState>("doc_undo"),
  docRedo: () => call<DocState>("doc_redo"),
  docGetState: () => call<DocState>("doc_get_state"),
  docGetMesh: () => call<MeshData>("doc_get_mesh"),
  docSave: (path: string) => call<DocState>("doc_save", { path }),
  docOpen: (path: string) => call<DocState>("doc_open", { path }),
  docExportStl: (path: string, linearDeflection?: number) =>
    call<ExportResult>("doc_export_stl", { path, linear_deflection: linearDeflection }),
  docNewTutorial: () => call<DocState>("doc_new_tutorial"),
  docSwitchSlot: (slot: "main" | "tutorial") => call<DocState>("doc_switch_slot", { slot }),
};
