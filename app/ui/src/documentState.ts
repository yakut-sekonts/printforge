import type { DocState, ImageReliefSettings } from "./types";

export function sameDocumentInstance(current: DocState, incoming: DocState): boolean {
  return current.slot === incoming.slot && current.doc_id === incoming.doc_id &&
    current.document_instance_id === incoming.document_instance_id;
}

export function acceptsDocumentState(current: DocState | null, incoming: DocState): boolean {
  return !current || !sameDocumentInstance(current, incoming) || incoming.revision >= current.revision;
}

export function documentGeometryChanged(current: DocState | null, incoming: DocState): boolean {
  return !current || !sameDocumentInstance(current, incoming) || current.revision !== incoming.revision;
}

export function isEditableTarget(target: EventTarget | null): boolean {
  return target instanceof Element && !!target.closest("input, textarea, select, [contenteditable]:not([contenteditable='false'])");
}

export function faceMeasurementIsCurrent(result: { faceIndex?: number } | null, selectedFace: number | null): boolean {
  return selectedFace != null && result?.faceIndex === selectedFace;
}

export function imageReliefSettingsKey(settings: ImageReliefSettings): string {
  return JSON.stringify([
    settings.path.trim(), settings.model, settings.seed, settings.width_mm,
    settings.relief_height, settings.base_thickness, settings.samples,
    settings.noise_strength, settings.invert,
  ]);
}
