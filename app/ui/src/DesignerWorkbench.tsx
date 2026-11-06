import React, { useEffect, useRef, useState } from "react";
import type { DocState, MeshData, Point3, FaceFeatureProfile, FaceAxis } from "./types";
import type { Viewport } from "./viewport";
import type { EdgeToolUi } from "./ParamsPanel";
import type { FaceFeatureTarget } from "./faceEditing";
import { faceFeatureArgs } from "./faceEditing";
import { constrainedSize, deformPositions, editableParameters, edgeDesignerAction, EDIT_FIELDS, operationName } from "./designer";
import type { DesignerAction } from "./designer";

type Mode = "dimensions" | "placement" | "sketch" | "sculpt" | "convert" | "history" | "history-list" | null;
type Preview = (action: DesignerAction, done: (error: string | null) => void) => () => void;

export function OperationHistory({ doc, onEdit, onSelect }: {
  doc: DocState | null; onEdit: (index: number) => void; onSelect: (id: string) => void;
}) {
  return <ol className="history-list">
    {(doc?.parts ?? []).map((part) => <li key={part.part_id}><button className="history-operation" onClick={() => onSelect(part.part_id)}>{part.name} · заготовка</button></li>)}
    {(doc?.operations ?? []).map((operation, index) => <li key={index}>
      <button className="history-operation" data-cmd="op.history_edit" onClick={() => {
        const id = operation.target_id ?? operation.part_id;
        if (id) onSelect(id);
        onEdit(index);
      }}>{index + 1}. {operationName(operation)}{operation.enabled === false ? " · выключено" : ""}</button>
    </li>)}
    {!doc?.operations?.length && <li className="panel-empty">Выберите форму. Изменения появятся здесь.</li>}
  </ol>;
}

function NumberField({ label, value, onChange, min, step = 0.1 }: {
  label: string; value: number; onChange: (value: number) => void; min?: number; step?: number;
}) {
  return <label className="designer-field">{label}<input type="number" step={step} min={min}
    value={Number.isFinite(value) ? value : ""} onChange={(event) => onChange(event.target.value === "" ? NaN : Number(event.target.value))} /></label>;
}

function ParameterFields({ value, onChange, prefix = "" }: {
  value: Record<string, unknown>; onChange: (value: Record<string, unknown>) => void; prefix?: string;
}) {
  const labels: Record<string, string> = { radius: "Радиус, мм", distance: "Расстояние, мм", size: "Габариты, мм",
    anchor: "Неподвижный угол", translate: "Перемещение, мм", rotate_deg: "Поворот, °", pivot: "Центр поворота, мм",
    depth: "Глубина, мм", diameter: "Диаметр, мм", width: "Ширина, мм", height: "Высота, мм", center: "Центр, мм", delta: "Смещение, мм" };
  return <>{Object.entries(value).map(([key, current]) => {
    const label = `${prefix}${labels[key] ?? key}`;
    const update = (next: unknown) => onChange({ ...value, [key]: next });
    if (typeof current === "number") return <NumberField key={key} label={label} value={current} onChange={update} />;
    if (Array.isArray(current) && current.every((item) => typeof item === "number")) return <fieldset key={key}><legend>{label}</legend><div className="designer-vector">
      {current.map((item, axis) => <NumberField key={axis} label={(current.length === 2 ? "UV" : "XYZ")[axis]} value={item} onChange={(next) => update(current.map((old, index) => index === axis ? next : old))} />)}
    </div></fieldset>;
    if (current && typeof current === "object" && !Array.isArray(current)) return <fieldset key={key}><legend>{label}</legend>
      <ParameterFields value={current as Record<string, unknown>} onChange={update} /></fieldset>;
    if (key === "mode") return <label key={key} className="designer-field">Действие<select value={String(current)} onChange={(event) => update(event.target.value)}><option value="add">Добавить</option><option value="cut">Вырезать</option></select></label>;
    if (key === "depth" && current === "through") return <label key={key}><input type="checkbox" checked onChange={() => update(5)} />Сквозной вырез</label>;
    if (key === "plane") return <label key={key}>Плоскость<select value={String(current)} onChange={(event) => update(event.target.value)}>{["XY", "XZ", "YZ"].map((plane) => <option key={plane}>{plane}</option>)}</select></label>;
    return null;
  })}</>;
}

export function DesignerWorkbench({ doc, mesh, viewport, partId, face, edge, busy, historyIndex, onHistoryClose,
  preview, clearPreview, commit, prepare, onResizePolicy, onEdgeSize, onEdgeKind, onEdgeCancel, onStartResize, onStartMove, onFaceActions, onHistoryPick, onPartSelect, sceneToolActive,
}: {
  doc: DocState; mesh: MeshData; viewport: Viewport | null; partId: string | null; face: FaceFeatureTarget | null;
  edge: EdgeToolUi; busy: boolean; historyIndex: number | null; onHistoryClose: () => void;
  preview: Preview; clearPreview: () => void; commit: (action: DesignerAction) => Promise<boolean>;
  prepare: () => void; onResizePolicy: (preserve: boolean) => void;
  onEdgeSize: (size: string) => void; onEdgeKind: (kind: "fillet" | "chamfer") => void; onEdgeCancel: () => void;
  onStartResize: () => void; onStartMove: () => void; onFaceActions: () => void;
  onHistoryPick: (index: number) => void; onPartSelect: (id: string) => void;
  sceneToolActive: boolean;
}) {
  const part = doc.stats?.parts?.find((candidate) => candidate.part_id === partId) ?? doc.stats?.parts?.[0];
  const bounds = part?.bbox ?? doc.stats?.bbox ?? [0, 0, 0, 1, 1, 1];
  const originalSize = bounds.slice(3).map((value, axis) => value - bounds[axis]) as Point3;
  const [mode, setMode] = useState<Mode>(null);
  const [context, setContext] = useState<{ x: number; y: number } | null>(null);
  const [size, setSize] = useState<Point3>(originalSize);
  const [preserve, setPreserve] = useState(!!part?.parametric_resize);
  const [translation, setTranslation] = useState<Point3>([0, 0, 0]);
  const [rotation, setRotation] = useState<Point3>([0, 0, 0]);
  const [grid, setGrid] = useState(1);
  const [snap, setSnap] = useState(true);
  const [shape, setShape] = useState<"circle" | "rectangle">("circle");
  const [profile, setProfile] = useState<FaceFeatureProfile | null>(null);
  const [depth, setDepth] = useState<number | "through">(5);
  const [featureMode, setFeatureMode] = useState<"add" | "cut">("cut");
  const [drawing, setDrawing] = useState(true);
  const [radius, setRadius] = useState(Math.max(0.1, Math.round(Math.max(...originalSize) / 3 * 10) / 10));
  const [sculpt, setSculpt] = useState<{ center: Point3; delta: Point3 } | null>(null);
  const [changes, setChanges] = useState<Record<string, unknown>>({});
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previewReady, setPreviewReady] = useState(false);
  const gesture = useRef<{ point: Point3; delta: Point3 } | null>(null);
  const sketchDepthStart = useRef(5);
  const current = useRef({ edge, depth });
  current.current = { edge, depth };
  const isMesh = !!doc.stats?.mesh_mode;
  const operation = historyIndex == null ? null : doc.operations?.[historyIndex];
  const edgeActive = mode == null && edge.active && !!edge.selected;

  const close = () => { clearPreview(); viewport?.setDesignerTool(null); setMode(null); setProfile(null); setSculpt(null); setContext(null); setError(null); onHistoryClose(); };
  const open = (next: Mode) => {
    clearPreview(); prepare(); onHistoryClose(); setContext(null); setMode(next); setError(null); setPreviewReady(false);
    setSize(originalSize); setTranslation([0, 0, 0]); setRotation([0, 0, 0]);
    setProfile(null); setSculpt(null); setDrawing(true);
  };

  useEffect(() => {
    if (historyIndex == null) { setMode((currentMode) => currentMode === "history" ? null : currentMode); return; }
    if (!operation) return;
    prepare(); setMode("history"); setChanges(editableParameters(operation)); setEnabled(operation.enabled !== false);
  }, [historyIndex]);

  useEffect(() => {
    if (!sceneToolActive) return;
    clearPreview(); setMode(null); onHistoryClose();
  }, [sceneToolActive]);

  useEffect(() => {
    if (!viewport) return;
    viewport.setDesignerContext((x, y) => setContext({ x, y }));
    viewport.setDimensionEditor(part?.bbox ?? null, isMesh ? null : () => open("dimensions"));
    return () => { viewport.setDesignerContext(null); viewport.setDimensionEditor(null, null); };
  }, [viewport, partId, doc.revision, isMesh]);

  useEffect(() => {
    onResizePolicy(preserve && !!part?.parametric_resize);
    viewport?.setResizeConstraint(preserve && part?.parametric_resize ? part.size_constraint ?? "free" : "free");
  }, [preserve, part?.parametric_resize, part?.size_constraint, viewport]);

  useEffect(() => {
    viewport?.setSnapping(snap && part?.bbox ? { bounds: part.bbox,
      others: (doc.stats?.parts ?? []).filter((candidate) => candidate.part_id !== part.part_id && candidate.bbox).map((candidate) => candidate.bbox!), grid } : null);
  }, [snap, grid, partId, doc.revision, viewport]);

  let action: DesignerAction | null = null;
  if (mode === "dimensions" && part) action = { type: "append", operation: { op: preserve && part.parametric_resize ? "resize_parametric" : "resize_body", target_id: part.part_id, size, anchor: [-1, -1, -1] } };
  if (mode === "placement" && part) action = { type: "append", operation: { op: isMesh ? "mesh_transform" : "transform", part_id: part.part_id, translate: translation, rotate_deg: rotation,
    pivot: bounds.slice(0, 3).map((value, axis) => (value + bounds[axis + 3]) / 2) } };
  if (mode === "sketch" && face && profile && !drawing) action = { type: "append", operation: { op: "face_feature", ...faceFeatureArgs(face, featureMode, profile, depth) } };
  if (mode === "sculpt" && sculpt) action = { type: "append", operation: { op: "mesh_deform", ...sculpt, radius } };
  if (mode === "history" && operation && EDIT_FIELDS[operation.op]) action = { type: "edit", index: historyIndex!, changes: { ...changes, enabled } };
  if (edgeActive && part && edge.selected) action = edgeDesignerAction(edge.kind, edge.selected, Number(edge.size), edge.partId ?? part.part_id);
  const actionKey = JSON.stringify(action);
  useEffect(() => {
    setPreviewReady(false); setError(null);
    if (!action || busy) { clearPreview(); return; }
    let cancel = () => {};
    const timer = window.setTimeout(() => {
      cancel = preview(action!, (cause) => { setError(cause); setPreviewReady(!cause); });
    }, 180);
    return () => { window.clearTimeout(timer); cancel(); };
  }, [actionKey, busy]);

  useEffect(() => {
    if (!viewport || busy) { viewport?.setDesignerTool(null); return; }
    if (mode === "sketch" && face && drawing) {
      viewport.setPushPullHandle(null);
      viewport.setDesignerTool({ kind: "sketch", origin: face.center, normal: face.normal,
        start: (point) => { gesture.current = { point, delta: [0, 0, 0] }; },
        move: (point) => {
          const start = gesture.current?.point;
          if (!start) return;
          const project = (axis: FaceAxis, source: Point3) => source["xyz".indexOf(axis)] - face.center["xyz".indexOf(axis)];
          const first = [project(face.uAxis, start), project(face.vAxis, start)];
          const last = [project(face.uAxis, point), project(face.vAxis, point)];
          const next: FaceFeatureProfile = shape === "circle" ? { kind: "circle", center: [first[0], first[1]], diameter: Math.max(0.1, 2 * Math.hypot(last[0] - first[0], last[1] - first[1])) }
            : { kind: "rectangle", center: [(first[0] + last[0]) / 2, (first[1] + last[1]) / 2], width: Math.max(0.1, Math.abs(last[0] - first[0])), height: Math.max(0.1, Math.abs(last[1] - first[1])) };
          setProfile(next);
          viewport.setFaceFeaturePreview({ target: face, args: faceFeatureArgs(face, featureMode, next, depth) });
        }, finish: (cancelled) => { if (cancelled) { setProfile(null); viewport.setFaceFeaturePreview(null); } else setDrawing(false); },
      });
    } else if (mode === "sketch" && face && profile && !drawing) {
      viewport.setDesignerTool(null);
      sketchDepthStart.current = typeof current.current.depth === "number" ? current.current.depth : 5;
      viewport.setDesignerPull({ ...face, parameter: "", label: "Глубина", current: 0, minimum: 0.1, deltaFactor: 1, symmetric: false }, (delta, finished) => {
        setDepth(Math.max(0.1, Math.round((sketchDepthStart.current + delta) * 10) / 10));
        if (finished) sketchDepthStart.current = Math.max(0.1, sketchDepthStart.current + delta);
      });
    } else if (mode === "sculpt" && isMesh) {
      viewport.setPushPullHandle(null);
      viewport.setDesignerTool({ kind: "sculpt", radius,
        start: (point) => { gesture.current = { point, delta: [0, 0, 0] }; },
        move: (_point, delta) => {
          if (!gesture.current) return;
          gesture.current.delta = delta;
          viewport.setOperationPreview({ ...mesh, positions: deformPositions(mesh.positions, gesture.current.point, delta, radius) });
        }, finish: (cancelled) => {
          if (cancelled) { viewport.setOperationPreview(null); return; }
          if (gesture.current) setSculpt({ center: gesture.current.point, delta: gesture.current.delta });
        },
      });
    } else if (edgeActive && edge.selected) {
      viewport.setDesignerTool({ kind: "edge", origin: edge.selected.midpoint,
        numeric: (value) => onEdgeSize(String(value)),
        start: (point) => { gesture.current = { point, delta: [Number(current.current.edge.size) || 1, 0, 0] }; },
        move: (_point, delta) => {
          const amount = Math.round(Math.max(0.1, (gesture.current?.delta[0] ?? 1) + delta[0] + delta[1]) * 10) / 10;
          onEdgeSize(String(amount));
        }, finish: (cancelled) => { if (cancelled) clearPreview(); },
      });
    } else viewport.setDesignerTool(null);
    return () => { viewport.setDesignerTool(null); viewport.setDesignerPull(null, null); };
  }, [mode, drawing, shape, face, isMesh, viewport, mesh, radius, busy, edgeActive, edge.selected]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { close(); if (edgeActive) onEdgeCancel(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  useEffect(() => () => { clearPreview(); viewport?.setDesignerTool(null); viewport?.setFaceFeaturePreview(null); }, []);

  const apply = async () => {
    if (!action || !previewReady || busy) return;
    if (await commit(action)) { if (edgeActive) onEdgeCancel(); close(); }
  };
  const policy = <label className="designer-field">Как менять габариты<select value={preserve && part?.parametric_resize ? "preserve" : "scale"} onChange={(event) => setPreserve(event.target.value === "preserve")}>
    <option value="preserve" disabled={!part?.parametric_resize}>Сохранять отверстия и радиусы</option><option value="scale">Масштабировать всё, включая отверстия</option></select></label>;
  const title = mode === "dimensions" ? "Размеры детали" : mode === "placement" ? "Положение детали" : mode === "sketch" ? "Эскиз на грани" : mode === "sculpt" ? "Мягкая форма · mesh" : mode === "history" ? operation ? operationName(operation) : "История" : mode === "history-list" ? "История операций" : mode === "convert" ? "Перейти в mesh?" : "Скругление / фаска";
  const otherParts = (doc.stats?.parts ?? []).filter((candidate) => candidate.part_id !== part?.part_id && candidate.bbox);
  const snappingControls = <div className="designer-snapping"><label><input type="checkbox" checked={snap} onChange={(event) => setSnap(event.target.checked)} />Привязки</label><label>Шаг<input aria-label="Шаг сетки, мм" className="designer-grid" type="number" min="0.1" step="0.1" value={grid} onChange={(event) => setGrid(Number(event.target.value))} />мм</label></div>;
  return <>
    <div className="designer-toolbar" role="toolbar" aria-label="Ручное проектирование">
      {!isMesh && <button className="btn" data-cmd="op.dimensions" disabled={busy} onClick={() => open("dimensions")}>Размеры</button>}
      <button className="btn" data-cmd="op.placement" disabled={busy} onClick={() => open("placement")}>Положение</button>
      {!isMesh && <button className="btn" data-cmd="op.face_sketch" disabled={busy || !face} title={face ? "Нарисуйте на выбранной грани" : "Выберите внешнюю плоскую грань"} onClick={() => open("sketch")}>Рисовать на грани</button>}
      <button className="btn" data-cmd="op.mesh_deform" disabled={busy} onClick={() => open(isMesh ? "sculpt" : "convert")}>Мягкая форма</button>
      <button className="btn" data-cmd="op.history_edit" disabled={busy} onClick={() => open("history-list")}>История</button>
    </div>
    {context && <div className="designer-context" role="menu" style={{ left: Math.min(context.x, window.innerWidth - 260), top: Math.min(context.y, window.innerHeight - 330) }}>
      <strong>{edge.selected ? "Ребро" : face ? "Грань" : "Деталь"}</strong>
      {edge.selected && <><button role="menuitem" onClick={() => { close(); onEdgeKind("fillet"); }}>Скруглить ребро</button><button role="menuitem" onClick={() => { close(); onEdgeKind("chamfer"); }}>Снять фаску</button></>}
      {face && <><button role="menuitem" onClick={() => open("sketch")}>Нарисовать круг / прямоугольник</button><button role="menuitem" onClick={() => { setContext(null); onFaceActions(); }}>Все действия с гранью</button></>}
      {!isMesh && <><button role="menuitem" onClick={() => open("dimensions")}>Задать размеры</button><button role="menuitem" onClick={() => { close(); onStartResize(); }}>Потянуть угол / сторону</button></>}
      <button role="menuitem" onClick={() => { close(); onStartMove(); }}>Перемещать мышью</button>
      <button role="menuitem" onClick={() => open("placement")}>Выровнять / повернуть</button>
      <button role="menuitem" onClick={() => setContext(null)}>Закрыть</button>
    </div>}
    {(mode || edgeActive) && <section className="designer-card" aria-label={title} data-cmd={mode === "history" ? "op.history_edit" : "op.designer"}>
      <header><strong>{title}</strong><button className="btn" aria-label="Закрыть инструмент" onClick={() => { close(); if (edgeActive) onEdgeCancel(); }}>×</button></header>
      {mode === "dimensions" && <>{policy}<div className="designer-vector">{size.map((value, axis) => <NumberField key={axis} label={`${"XYZ"[axis]}, мм`} value={value} min={0.01} onChange={(next) => {
        try { setSize(constrainedSize(size, axis, next, preserve && part?.parametric_resize ? part.size_constraint : "free")); } catch { setSize(size.map((old, index) => index === axis ? next : old) as Point3); }
      }} />)}</div><p>Минимальный угол неподвижен. Двойной щелчок по размеру в сцене открывает этот инструмент.</p>
      {!part?.parametric_resize && <p>Для этой истории доступно только масштабирование всего тела.</p>}</>}
      {mode === "placement" && <>{snappingControls}<ParameterFields value={{ translate: translation, rotate_deg: rotation }} onChange={(value) => { setTranslation(value.translate as Point3); setRotation(value.rotate_deg as Point3); }} />
        {otherParts.length > 0 && <fieldset><legend>Совместить с другой деталью</legend>{otherParts.map((other) => <div key={other.part_id}><span>{other.name}</span>{[0, 1, 2].map((axis) => <span key={axis} className="designer-align">{"XYZ"[axis]}{["min", "center", "max"].map((align) => <button className="btn" key={align} onClick={() => {
          const box = other.bbox!, coordinate = (source: number[]) => align === "min" ? source[axis] : align === "max" ? source[axis + 3] : (source[axis] + source[axis + 3]) / 2;
          setTranslation(translation.map((value, index) => index === axis ? coordinate(box) - coordinate(bounds) : value) as Point3);
        }}>{align === "min" ? "−" : align === "max" ? "+" : "Ц"}</button>)}</span>)}</div>)}</fieldset>}
        <p>Поворот вокруг центра детали. Привязки работают при перетягивании стрелок; Shift — 0,1 мм, Alt — без привязки к телам.</p></>}
      {mode === "sketch" && <><div className="designer-buttons"><button className="btn" aria-pressed={shape === "circle"} onClick={() => { setShape("circle"); setDrawing(true); }}>Круг</button><button className="btn" aria-pressed={shape === "rectangle"} onClick={() => { setShape("rectangle"); setDrawing(true); }}>Прямоугольник</button><button className="btn" onClick={() => { setProfile(null); setDrawing(true); clearPreview(); }}>Перерисовать</button></div>
        <p>{drawing ? "Зажмите мышь на грани и потяните: круг — от центра, прямоугольник — из угла." : "Контур готов. Задайте глубину или потяните стрелку нормали."}</p>
        {profile && <ParameterFields value={profile as unknown as Record<string, unknown>} onChange={(value) => setProfile(value as unknown as FaceFeatureProfile)} />}
        <label>Действие<select value={featureMode} onChange={(event) => { setFeatureMode(event.target.value as "add" | "cut"); if (event.target.value === "add" && depth === "through") setDepth(5); }}><option value="cut">Вырезать</option><option value="add">Выдавить</option></select></label>
        <label><input type="checkbox" disabled={featureMode === "add"} checked={depth === "through"} onChange={(event) => setDepth(event.target.checked ? "through" : 5)} />Насквозь</label>
        {depth !== "through" && <NumberField label="Глубина, мм" min={0.1} value={depth} onChange={setDepth} />}</>}
      {mode === "sculpt" && <><NumberField label="Радиус кисти, мм" value={radius} min={0.1} onChange={setRadius} /><p>Зажмите поверхность и потяните. Изменение мягко затухает внутри радиуса. После Preview нажмите «Применить».</p><p>Сетка, не точный CAD. STEP недоступен. Инверсия треугольников проверяется; общий self-intersection solver отсутствует.</p></>}
      {mode === "convert" && <><p>Точная модель будет заменена плотной треугольной сеткой. Отверстия и радиусы больше не параметрические; экспорт STEP недоступен. Cmd/Ctrl+Z вернёт исходный BRep.</p><button className="btn btn-primary" disabled={busy} onClick={async () => { if (await commit({ type: "convert_mesh" })) close(); }}>Преобразовать в mesh</button></>}
      {mode === "history" && operation && <>{EDIT_FIELDS[operation.op] ? <><ParameterFields value={changes} onChange={setChanges} /><label><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />Операция включена</label><p>Preview перестраивает последующие операции. Ошибка не меняет модель и историю Undo/Redo.</p></> : <p>Этот тип операции пока доступен только для просмотра. Исходник нельзя отключать.</p>}</>}
      {mode === "history-list" && <OperationHistory doc={doc} onEdit={onHistoryPick} onSelect={onPartSelect} />}
      {edgeActive && <><div className="designer-buttons"><button className="btn" aria-pressed={edge.kind === "fillet"} onClick={() => onEdgeKind("fillet")}>Скругление</button><button className="btn" aria-pressed={edge.kind === "chamfer"} onClick={() => onEdgeKind("chamfer")}>Фаска</button></div><NumberField label={edge.kind === "fillet" ? "Радиус, мм" : "Фаска, мм"} value={Number(edge.size)} min={0.1} onChange={(value) => onEdgeSize(String(value))} /><p>Потяните синюю ручку на ребре. Точный Preview после отпускания; модель меняется только по «Применить».</p></>}
      {mode !== "convert" && mode !== "history-list" && <><p className={error ? "designer-error" : "designer-preview"} role="status">{error ?? (previewReady ? "Точный Preview готов · модель ещё не изменена" : action ? "Подготовка Preview…" : "Выберите область и задайте изменение")}</p><button className="btn btn-primary" disabled={busy || !previewReady || !action} onClick={() => void apply()}>Применить</button><button className="btn" onClick={() => { close(); if (edgeActive) onEdgeCancel(); }}>Отмена</button></>}
    </section>}
    {!mode && !edgeActive && <div className="designer-policy">{!isMesh && policy}{snappingControls}</div>}
  </>;
}
