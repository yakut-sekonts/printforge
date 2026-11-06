import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { DocState, MeshData, SurfaceRef } from "./types";
import type { Viewport } from "./viewport";
import type { DesignerAction } from "./designer";
import { solidIndicesForParts, partIdForSolid } from "./sceneSelection";

type Preview = (action: DesignerAction, done: (error: string | null) => void) => () => void;
type SurfacePick = { partId: string; surface: SurfaceRef };

export function InteractionTools({ doc, mesh, viewport, selectedFace, selectedPartId, busy, inspectMode, onClearSelection,
  onHistoryPick, preview, clearPreview, commit, prepare, active, onFinish, suspended, dock,
}: {
  doc: DocState; mesh: MeshData; viewport: Viewport | null; selectedFace: number | null; selectedPartId: string | null;
  busy: boolean; inspectMode: boolean; onClearSelection: () => void; onHistoryPick: (index: number) => void;
  preview: Preview; clearPreview: () => void; commit: (action: DesignerAction) => Promise<boolean>; prepare: () => void;
  active: boolean; onFinish: () => void;
  suspended: boolean;
  dock: HTMLElement | null;
}) {
  const [hint, setHint] = useState("Выберите тело, грань или ребро");
  const [hidden, setHidden] = useState<string[]>([]);
  const [moving, setMoving] = useState<SurfacePick | null>(null);
  const [fixed, setFixed] = useState<SurfacePick | null>(null);
  const [gap, setGap] = useState(0);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parts = doc.stats?.parts ?? [];
  const range = mesh.face_ranges.find((candidate) => candidate.face_index === selectedFace);
  const selectedId = range?.solid_index == null ? null : partIdForSolid(parts, range.solid_index);
  const selectedSurface = range?.surface_ref && selectedId ? { partId: selectedId, surface: range.surface_ref } : null;
  const identity = `${doc.document_instance_id}:${doc.slot}`;

  useEffect(() => { viewport?.setSelectionHint(setHint); return () => viewport?.setSelectionHint(null); }, [viewport]);
  useEffect(() => { setHidden([]); setMoving(null); setFixed(null); setError(null); }, [identity]);
  useEffect(() => { if (!active) { setMoving(null); setFixed(null); } }, [active]);
  useEffect(() => {
    setMoving(null); setFixed(null); setReady(false);
  }, [doc.revision]);
  useEffect(() => { viewport?.setHiddenSolids(solidIndicesForParts(parts, hidden)); }, [viewport, mesh, hidden.join()]);

  const action: DesignerAction | null = moving && fixed ? { type: "append", operation: { op: "mate", kind: moving.surface.kind === "plane" ? "plane" : "axis",
    part_id: moving.partId, fixed_id: fixed.partId, moving_surface: moving.surface, fixed_surface: fixed.surface, gap } } : null;
  useEffect(() => {
    setReady(false); setError(null);
    if (!action || busy || inspectMode) return;
    return preview(action, (cause) => { setError(cause); setReady(!cause); });
  }, [JSON.stringify(action), busy, inspectMode]);
  const hide = () => {
    if (!selectedPartId) return;
    setHidden((current) => [...new Set([...current, selectedPartId])]); onClearSelection();
  };
  const cancel = () => { clearPreview(); setMoving(null); setFixed(null); setError(null); onFinish(); };
  if (suspended) return null;
  return <>
    {dock && createPortal(<div className="interaction-controls">
    <div className="selection-hint" role="status">{hint}</div>
    <div className="interaction-toolbar" role="toolbar" aria-label="Выбор и сборка">
      <button className="btn" data-cmd="view.hide_body" disabled={busy || inspectMode || !selectedPartId} onClick={hide}>Скрыть деталь</button>
      <button className="btn" data-cmd="view.show_bodies" disabled={busy || inspectMode || !hidden.length} onClick={() => setHidden([])}>Показать все{hidden.length ? ` (${hidden.length})` : ""}</button>
      {range?.feature_index != null && <button className="btn" data-cmd="op.local_feature" disabled={busy || inspectMode} onClick={() => onHistoryPick(range.feature_index!)}>Изменить этот элемент</button>}
      {!moving ? <button className="btn" data-cmd="op.mate" disabled={busy || inspectMode || !selectedSurface} onClick={() => {
        prepare(); setMoving(selectedSurface); setFixed(null); setGap(0);
      }}>Соединить по поверхности</button> : <button className="btn" disabled={busy || inspectMode || !selectedSurface || selectedSurface.partId === moving.partId || selectedSurface.surface.kind !== moving.surface.kind} onClick={() => setFixed(selectedSurface)}>Выбрать ответную поверхность</button>}
      {!doc.stats?.mesh_mode && selectedPartId && <button className="btn" data-cmd="op.place_on_bed" title="Для связанной детали сначала выключите сборочную связь в истории" disabled={busy || inspectMode || !!moving || (doc.operations ?? []).some((operation) => operation.op === "mate" && operation.part_id === selectedPartId && operation.enabled !== false)} onClick={() => {
        const part = parts.find((candidate) => candidate.part_id === selectedPartId);
        if (!part?.bbox) return;
        prepare(); void commit({ type: "append", operation: { op: "transform", part_id: selectedPartId,
          translate: [-(part.bbox[0] + part.bbox[3]) / 2, -(part.bbox[1] + part.bbox[4]) / 2, -part.bbox[2]] } });
      }}>На центр стола</button>}
    </div>
    </div>, dock)}
    {moving && <section className="mate-card" aria-label="Сборочная связь">
      <strong>{moving.surface.kind === "plane" ? "Приложить грань к грани" : "Совместить оси"}</strong>
      <p>{fixed ? "Ответная поверхность выбрана. Детали останутся отдельными." : "Выберите подходящую поверхность другой детали и нажмите «Выбрать ответную поверхность»."}</p>
      <label className="designer-field">{moving.surface.kind === "plane" ? "Зазор, мм" : "Осевое смещение, мм"}<input type="number" step="0.1" value={Number.isFinite(gap) ? gap : ""} onChange={(event) => setGap(event.target.value === "" ? NaN : Number(event.target.value))} /></label>
      <p>Плоская связь совмещает центры и противоположные нормали; осевая — оси и осевые уровни центров поверхностей. Это направленная связь, не полный сборочный solver. Изменение топологии требует повторного выбора.</p>
      <p role="status" className={error ? "designer-error" : "designer-preview"}>{error ?? (ready ? "Точный Preview готов" : fixed ? "Подготовка Preview…" : "Ожидание выбора")}</p>
      <button className="btn btn-primary" disabled={!action || !ready || busy || inspectMode} onClick={async () => { if (action && await commit(action)) cancel(); }}>Применить связь</button>
      <button className="btn" onClick={cancel}>Отмена</button>
    </section>}
  </>;
}
