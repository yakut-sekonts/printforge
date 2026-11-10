import React, { useEffect, useRef, useState } from "react";
import { backend, parseIpcError } from "./backend";
import { addSketchContour, addSketchEntity, arcPolyline, checkpointSketchContour, describeSketchConstraint, pointsAfterToolChange, setSketchDimension, sketchDimensionValue, sketchForRadiusDrag, sketchPairActions, sketchPoints, snapSketchPoint } from "./sketchEditing";
import type { ConstrainedSketch, ConstrainedSketchEntity, Point2, SketchConstraint, SketchDrag, SketchPointRef, SketchSolveResult } from "./types";

const EMPTY: ConstrainedSketch = { entities: [], constraints: [], regions: [] };

export function SketchCanvas({ width, height, initial, onChange, onClose, onDraft }: {
  width: number; height: number; initial?: ConstrainedSketch;
  onChange: (sketch: ConstrainedSketch | null) => void; onClose: () => void;
  onDraft: (sketch: ConstrainedSketch) => void;
}) {
  const [sketch, setSketch] = useState<ConstrainedSketch>(initial ?? EMPTY);
  const [tool, setTool] = useState<"select" | "line" | "arc" | "circle">("line");
  const [points, setPoints] = useState<Point2[]>([]);
  const [chain, setChain] = useState<string[]>([]);
  const [hole, setHole] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [dimension, setDimension] = useState(10);
  const [solution, setSolution] = useState<SketchSolveResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<number[]>([]);
  const [solving, setSolving] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [cursor, setCursor] = useState<Point2 | null>(null);
  const [drag, setDrag] = useState<SketchDrag | null>(null);
  const [finishDrag, setFinishDrag] = useState(false);
  const [dragError, setDragError] = useState<string | null>(null);
  const [undo, setUndo] = useState<ConstrainedSketch[]>([]);
  const sequence = useRef(0);
  const mounted = useRef(true);
  const current = useRef(sketch);
  const svg = useRef<SVGSVGElement>(null);
  const radiusCenter = useRef<Point2>([0, 0]);
  const dragStart = useRef<SketchDrag | null>(null);
  const contourStart = useRef<ReturnType<typeof checkpointSketchContour> | null>(null);
  current.current = sketch;
  const spanX = Math.max(20, width * 1.2) / zoom, spanY = Math.max(20, height * 1.2) / zoom;
  const pointRadius = Math.max(spanX, spanY) / 160;

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; sequence.current += 1; }; }, []);
  useEffect(() => { onDraft(sketch); }, [JSON.stringify(sketch)]);
  useEffect(() => {
    const token = ++sequence.current;
    onChange(null); setSolution(null); setError(null); setConflicts([]);
    if (!sketch.entities.length) { setSolving(false); return; }
    setSolving(true);
    const timer = window.setTimeout(() => {
      const candidate = drag && "radius" in drag ? sketchForRadiusDrag(sketch, drag.entity, drag.radius) : sketch;
      void backend.sketchSolve(candidate, drag ?? undefined).then((result) => {
        if (!mounted.current || token !== sequence.current) return;
        setSolution(result); setSolving(false);
        if (finishDrag && drag) {
          setUndo((history) => [...history.slice(-49), sketch]); setSketch({ ...candidate, entities: result.entities }); setDrag(null); setFinishDrag(false);
          if ("radius" in drag) {
            const circle = result.entities.find((entity) => entity.id === drag.entity);
            if (circle?.type === "circle") setDimension(Math.round(circle.radius * 100) / 100);
          }
          return;
        }
        if (!drag && !chain.length && !points.length && (candidate.regions?.length ?? 0) > 0) onChange({ ...candidate, entities: result.entities });
      }).catch((cause) => { if (mounted.current && token === sequence.current) {
        const parsed = parseIpcError(cause);
        setError(parsed.message); setSolving(false); setFinishDrag(false);
        if (finishDrag && drag) { setDragError(parsed.message); setDrag(null); }
        try { const detail = typeof parsed.detail === "string" ? JSON.parse(parsed.detail) : parsed.detail; setConflicts(Array.isArray(detail?.conflicting_constraints) ? detail.conflicting_constraints : []); } catch { setConflicts([]); }
      } });
    }, 100);
    return () => { window.clearTimeout(timer); sequence.current += 1; };
  }, [JSON.stringify(sketch), JSON.stringify(drag), chain.length, points.length, finishDrag]);

  const change = (next: ConstrainedSketch, recordUndo = true) => {
    const previous = current.current;
    if (recordUndo) setUndo((history) => [...history.slice(-49), previous]);
    setSketch(next); setDrag(null); setFinishDrag(false); setDragError(null);
  };
  const coordinate = (event: React.PointerEvent<SVGSVGElement>): Point2 => {
    const element = svg.current!;
    const matrix = element.getScreenCTM();
    if (!matrix) return [0, 0];
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    return [point.x, -point.y];
  };
  const addEntity = (entity: ConstrainedSketchEntity) => {
    try {
      let next = addSketchEntity(sketch, entity);
      if (entity.type === "circle") next = addSketchContour(next, entity.id, hole);
      else {
        const nextChain = [...chain, entity.id];
        const first = next.entities.find((candidate) => candidate.id === nextChain[0]);
        if (first && first.type !== "circle" && Math.hypot(entity.end[0] - first.start[0], entity.end[1] - first.start[1]) < 1e-5 && nextChain.length >= 2) {
          next = addSketchContour(next, nextChain, hole);
          const previous = contourStart.current?.sketch ?? sketch;
          setUndo((history) => [...history.slice(-49), previous]);
          setChain([]); setPoints([]); contourStart.current = null;
        } else {
          if (!chain.length) contourStart.current = checkpointSketchContour(sketch, undo);
          setChain(nextChain); setPoints([entity.end]);
        }
      }
      change(next, entity.type === "circle");
    } catch (cause) { setError(String(cause instanceof Error ? cause.message : cause)); }
  };
  const click = (event: React.PointerEvent<SVGSVGElement>) => {
    if (tool === "select") return;
    const raw = coordinate(event);
    const point = snapSketchPoint(sketch, raw, pointRadius * 3).point;
    if (!points.length) { setPoints([point]); return; }
    const id = `element-${Math.max(0, ...sketch.entities.map((entity) => Number(entity.id.replace("element-", "")) || 0)) + 1}`;
    if (tool === "circle") {
      addEntity({ id, type: "circle", center: points[0], radius: Math.hypot(point[0] - points[0][0], point[1] - points[0][1]) }); setPoints([]);
    } else if (tool === "line") addEntity({ id, type: "line", start: points[0], end: point });
    else if (points.length === 1) setPoints([points[0], point]);
    else addEntity({ id, type: "arc", start: points[0], mid: points[1], end: point });
  };
  const constrain = (constraint: SketchConstraint) => change({ ...sketch, constraints: [...sketch.constraints, constraint] });
  const setChosenDimension = (entity: ConstrainedSketchEntity) => {
    if (entity.type === "arc") return;
    const next = setSketchDimension(sketch, entity.id, entity.type === "circle" ? "radius" : "length", dimension);
    if (next !== sketch) change(next);
  };
  const chosen = sketch.entities.find((entity) => entity.id === selected[0]);
  const displayed = solution?.entities ?? sketch.entities;
  const pairActions = sketchPairActions(chosen, sketch.entities.find((entity) => entity.id === selected[1]));
  return <div className="sketch-workspace">
    <div className="sketch-canvas-toolbar" role="toolbar" aria-label="Инструменты эскиза">
      {([['select', 'Выбор / точки'], ['line', 'Линия'], ['arc', 'Дуга · 3 точки'], ['circle', 'Окружность']] as const).map(([name, label]) => <button key={name} className="btn" aria-pressed={tool === name} disabled={!!chain.length && (name === "select" || name === "circle")} onClick={() => { if (name !== tool) { setTool(name); setPoints(pointsAfterToolChange(points, !!chain.length)); } }}>{label}</button>)}
      <label><input type="checkbox" checked={hole} disabled={!!chain.length || !!points.length} onChange={(event) => setHole(event.target.checked)} />Следующий контур — отверстие</label>
      <button className="btn" disabled={!undo.length || !!chain.length || !!points.length} onClick={() => { const previous = undo[undo.length - 1]; setSketch(previous); setUndo(undo.slice(0, -1)); setChain([]); setPoints([]); setDrag(null); setDragError(null); const entity = previous.entities.find((item) => item.id === selected[0]); if (entity) { const value = sketchDimensionValue(previous, entity); if (value !== null) setDimension(value); } }}>Назад в эскизе</button>
      <button className="btn" disabled={!chain.length && !points.length} onClick={() => {
        if (contourStart.current) { setSketch(contourStart.current.sketch); setUndo(contourStart.current.undo); }
        contourStart.current = null; setChain([]); setPoints([]); setCursor(null); setError(null); setConflicts([]);
      }}>Отменить незаконченный контур</button>
      <button className="btn" onClick={() => setZoom((value) => Math.max(0.1, value / 1.5))}>Отдалить</button><button className="btn" onClick={() => setZoom((value) => Math.min(20, value * 1.5))}>Приблизить</button>
      <button className="btn" disabled={solving || !!error || !solution || !!chain.length || !!points.length || !!drag} onClick={onClose}>К модели</button>
    </div>
    <svg className="sketch-canvas" ref={svg} viewBox={`${-spanX / 2} ${-spanY / 2} ${spanX} ${spanY}`} role="application" aria-label="Эскиз на выбранной грани в миллиметрах" onPointerDown={click}
      onPointerMove={(event) => {
        const point = coordinate(event); setCursor(point);
        if (drag && event.buttons === 1) setDrag("point" in drag ? { ...drag, value: point } : {
          ...drag, radius: Math.max(0.01, Math.round(Math.hypot(point[0] - radiusCenter.current[0], point[1] - radiusCenter.current[1]) * 100) / 100),
        });
      }} onPointerUp={() => {
        if (!drag) return;
        const start = dragStart.current;
        if (start && (("point" in start && "point" in drag && Math.hypot(start.value[0] - drag.value[0], start.value[1] - drag.value[1]) < 1e-6) ||
          ("radius" in start && "radius" in drag && Math.abs(start.radius - drag.radius) < 1e-6))) { setDrag(null); return; }
        setFinishDrag(true);
      }} onPointerCancel={() => { setDrag(null); setFinishDrag(false); }}>
      <rect x={-width / 2} y={-height / 2} width={width} height={height} fill="var(--active)" stroke="var(--muted)" strokeWidth={pointRadius / 3} />
      <line x1={-spanX / 2} y1="0" x2={spanX / 2} y2="0" stroke="var(--control)" strokeWidth={pointRadius / 4} /><line x1="0" y1={-spanY / 2} x2="0" y2={spanY / 2} stroke="var(--control)" strokeWidth={pointRadius / 4} />
      {displayed.map((entity) => <g key={entity.id} stroke={selected.includes(entity.id) ? "var(--accent)" : solution?.degrees_of_freedom === 0 ? "var(--positive)" : "var(--text)"} strokeWidth={pointRadius / 2} fill="none" onPointerDown={(event) => {
        if (tool !== "select") return;
        event.stopPropagation(); setSelected(event.shiftKey ? [...new Set([...selected, entity.id])].slice(-2) : [entity.id]);
        const value = sketchDimensionValue(sketch, entity); if (value !== null) setDimension(value);
      }}>
        {entity.type === "circle" ? <circle cx={entity.center[0]} cy={-entity.center[1]} r={entity.radius} /> : entity.type === "line" ? <line x1={entity.start[0]} y1={-entity.start[1]} x2={entity.end[0]} y2={-entity.end[1]} /> : <polyline points={arcPolyline(entity).map((point) => `${point[0]},${-point[1]}`).join(" ")} />}
        {tool === "select" && sketchPoints(entity).map(({ ref, point }) => <circle key={ref[1]} cx={point[0]} cy={-point[1]} r={pointRadius} fill="var(--surface)" onPointerDown={(event) => {
          event.stopPropagation(); svg.current?.setPointerCapture(event.pointerId); setSelected([entity.id]); setDragError(null);
          dragStart.current = { point: ref, value: point }; setDrag(dragStart.current);
        }} />)}
        {tool === "select" && entity.type === "circle" && <circle cx={entity.center[0] + entity.radius} cy={-entity.center[1]} r={pointRadius * 1.3} fill="var(--accent)" aria-label="Изменить радиус окружности" onPointerDown={(event) => {
          event.stopPropagation(); svg.current?.setPointerCapture(event.pointerId); setSelected([entity.id]); setDragError(null);
          radiusCenter.current = entity.center; setDimension(sketchDimensionValue(sketch, entity) ?? entity.radius);
          dragStart.current = { entity: entity.id, radius: entity.radius }; setDrag(dragStart.current);
        }} />}
      </g>)}
      {points.length > 0 && cursor && <polyline points={[...points, cursor].map((point) => `${point[0]},${-point[1]}`).join(" ")} fill="none" stroke="var(--accent)" strokeWidth={pointRadius / 3} strokeDasharray={`${pointRadius} ${pointRadius}`} />}
    </svg>
    <div className="sketch-properties">
      <strong>Эскиз · мм</strong><p>Линию продолжайте щелчками; замкните её в начальную точку. Дуга: начало, промежуточная точка, конец. В одном контуре можно переключаться между линией и дугой. Для второго контура сначала замкните первый. В режиме выбора потяните ручку на окружности, чтобы изменить радиус. Shift+щелчок выбирает два элемента.</p>
      <p role="status" className={error ? "designer-error" : ""}>{error ?? (solving ? "Проверка ограничений…" : solution ? `Свободных степеней: ${solution.degrees_of_freedom}; невязка ${solution.max_residual.toPrecision(2)}` : "Нарисуйте контур")}</p>
      {dragError && <p role="alert" className="designer-error">Не удалось изменить эскиз: {dragError}</p>}
      {drag && "radius" in drag && <p role="status">Радиус: {(solving ? drag.radius : (displayed.find((entity) => entity.id === drag.entity && entity.type === "circle") as Extract<ConstrainedSketchEntity, { type: "circle" }> | undefined)?.radius ?? drag.radius).toFixed(2)} мм</p>}
      {cursor && <p>U {cursor[0].toFixed(2)} · V {cursor[1].toFixed(2)} мм</p>}
      {chosen && !chain.length && !points.length && <><p>Выбран: {chosen.id}</p><div className="designer-buttons">
        {chosen.type === "line" && <><button className="btn" onClick={() => constrain({ type: "horizontal", entity: chosen.id })}>Горизонтально</button><button className="btn" onClick={() => constrain({ type: "vertical", entity: chosen.id })}>Вертикально</button></>}
        <button className="btn" onClick={() => constrain({ type: "fix", entity: chosen.id })}>Закрепить</button>
        {pairActions.equal && <button className="btn" onClick={() => constrain({ type: "equal", a: selected[0], b: selected[1] })}>Равные</button>}
        {pairActions.directional && <><button className="btn" onClick={() => constrain({ type: "parallel", a: selected[0], b: selected[1] })}>Параллельно</button><button className="btn" onClick={() => constrain({ type: "perpendicular", a: selected[0], b: selected[1] })}>Перпендикулярно</button></>}
      </div>{chosen.type !== "arc" && <label className="designer-field">{chosen.type === "circle" ? "Радиус" : "Длина"}, мм<input type="number" min="0.01" step="0.1" value={Number.isFinite(dimension) ? dimension : ""} onChange={(event) => setDimension(Number(event.target.value))} /><button className="btn" disabled={!Number.isFinite(dimension) || dimension <= 0} onClick={() => setChosenDimension(chosen)}>Задать размер</button></label>}</>}
      <ol className="sketch-constraints">{sketch.constraints.map((constraint, index) => <li key={index} className={conflicts.includes(index) ? "designer-error" : ""}><span>{conflicts.includes(index) ? "Конфликт · " : ""}{describeSketchConstraint(constraint)}</span><button className="btn" disabled={!!chain.length || !!points.length} aria-label={`Удалить ограничение ${index + 1}`} onClick={() => change({ ...sketch, constraints: sketch.constraints.filter((_, position) => position !== index) })}>Убрать</button></li>)}</ol>
      {!!chain.length && <p>Контур не замкнут: продолжите до начальной точки или отмените незаконченный контур.</p>}
    </div>
  </div>;
}
