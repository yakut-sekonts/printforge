import React from "react";
import type { EdgeFeatureKind } from "./types";
import type { EdgeToolUi, PushPullUi } from "./ParamsPanel";
import type { TransformAxis } from "./viewport";
import { parseMillimeters } from "./sceneSelection";
import { sizeLabel } from "./bodyResizing";
import type { Size3 } from "./bodyResizing";

type SplitPlane = "XY" | "XZ" | "YZ";
type BooleanKind = "union" | "subtract" | "intersect";

interface Props {
  hasBody: boolean;
  busy: boolean;
  selectedFace: number | null;
  faceArea: number | null;
  canAddFaceFeature: boolean;
  selectedPartName: string | null;
  selectedPartId: string | null;
  selectedPartIds: string[];
  parts: Array<{ part_id: string; name: string }>;
  pushPull: PushPullUi;
  edgeTool: EdgeToolUi;
  moveMode: boolean;
  bodyResizeMode: boolean;
  bodyResizeSize: Size3 | null;
  canResizeBody: boolean;
  onStartBodyResize: () => void;
  onCancelBodyResize: () => void;
  movePreview: { axis: TransformAxis; delta: number } | null;
  splitDefaults: Record<SplitPlane, number>;
  onStartEdgeTool: (kind: EdgeFeatureKind) => void;
  onStartMove: () => void;
  onCancelMove: () => void;
  onMoveExact: (axis: TransformAxis, delta: number) => void;
  onMovePreview: (axis: TransformAxis, delta: number) => void;
  onBoolean: (kind: BooleanKind, targetId: string, toolId: string, keepTool: boolean) => void;
  onSplit: (plane: SplitPlane, offset: number) => void;
  onSplitPreview: (plane: SplitPlane | null, offset?: number) => void;
  onPushPullValue: (value: string) => void;
  onApplyPushPull: () => void;
  onCancelPushPull: () => void;
  onEdgeToolSize: (value: string) => void;
  onApplyEdgeTool: () => void;
  onCancelEdgeTool: () => void;
  onShowFaceActions: () => void;
}

function formatNumber(value: number): string {
  return String(Math.round(value * 100) / 100);
}

export function SelectionCoach(props: Props) {
  const [splitOpen, setSplitOpen] = React.useState(false);
  const [splitPlane, setSplitPlane] = React.useState<SplitPlane>("YZ");
  const [splitOffset, setSplitOffset] = React.useState(() => String(props.splitDefaults.YZ));
  const [moveAxis, setMoveAxis] = React.useState<TransformAxis>("x");
  const [moveValue, setMoveValue] = React.useState("10");
  const [booleanOpen, setBooleanOpen] = React.useState(false);
  const [targetId, setTargetId] = React.useState(props.selectedPartIds[0] ?? props.selectedPartId ?? "");
  const [toolId, setToolId] = React.useState(props.selectedPartIds[1] ?? "");
  const [booleanKind, setBooleanKind] = React.useState<BooleanKind>("union");
  const [keepTool, setKeepTool] = React.useState(false);
  const selectionKey = props.selectedPartIds.join("|");

  React.useEffect(() => {
    setTargetId(props.selectedPartIds[0] ?? props.selectedPartId ?? "");
    setToolId(props.selectedPartIds[1] ?? "");
  }, [selectionKey, props.selectedPartId]);

  React.useEffect(() => () => props.onSplitPreview(null), []);
  React.useEffect(() => {
    if (props.moveMode || props.bodyResizeMode || props.edgeTool.active) {
      setSplitOpen(false);
      props.onSplitPreview(null);
    }
  }, [props.moveMode, props.bodyResizeMode, props.edgeTool.active]);

  if (!props.hasBody) return null;
  const frame = (children: React.ReactNode) => (
    <fieldset className="selection-coach" aria-label="Действия с выбранной областью" disabled={props.busy}>
      {children}
    </fieldset>
  );
  const edgeButtons = <>
    <button className="btn" onClick={() => props.onStartEdgeTool("fillet")}>Скруглить ребро</button>
    <button className="btn" onClick={() => props.onStartEdgeTool("chamfer")}>Сделать фаску</button>
  </>;

  if (props.bodyResizeMode) return frame(<>
    <div className="selection-coach-copy">
      <span className="selection-coach-kind">Форма мышью · {props.selectedPartName}</span>
      <strong aria-live="polite">{props.bodyResizeSize ? sizeLabel(props.bodyResizeSize)
        : props.selectedPartId ? "Потяните ручку на рамке тела" : "Выберите тело на сцене"}</strong>
      <span>Синие углы — пропорционально. Цветные ручки на сторонах — размер по X / Y / Z. Противоположная сторона неподвижна. Меняется всё тело, включая отверстия и радиусы.</span>
      <span>Шаг 1 мм · Shift — 0,1 мм · Отпустите мышь, чтобы применить · Esc — отмена · Cmd/Ctrl+Z — назад.</span>
    </div>
    <div className="selection-coach-actions">
      {edgeButtons}
      <button className="btn" onClick={props.onCancelBodyResize}>Завершить изменение формы</button>
    </div>
  </>);

  if (props.edgeTool.active) {
    const size = parseMillimeters(props.edgeTool.size);
    return frame(<>
      <div className="selection-coach-copy">
        <span className="selection-coach-kind">Обработка ребра</span>
        <strong>{props.edgeTool.kind === "fillet" ? "Скругление" : "Фаска"}</strong>
        <span>{props.edgeTool.selected ? "Задайте точный размер и примените. Отмена сохраняет исходную форму."
          : "Наведите на ребро: синяя подсветка показывает выбор. Нажмите на него."}</span>
      </div>
      <div className="selection-coach-actions">
        <label className="selection-size">
          <span>{props.edgeTool.kind === "fillet" ? "Радиус" : "Размер"}</span>
          <input inputMode="decimal" value={props.edgeTool.size}
            aria-label={props.edgeTool.kind === "fillet" ? "Радиус скругления, мм" : "Размер фаски, мм"}
            onChange={(event) => props.onEdgeToolSize(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter" && size != null && size > 0 && props.edgeTool.selected) props.onApplyEdgeTool(); }} />
          <span>мм</span>
        </label>
        <button className="btn btn-primary" disabled={!props.edgeTool.selected || size == null || size <= 0} onClick={props.onApplyEdgeTool}>Применить</button>
        <button className="btn" onClick={props.onCancelEdgeTool}>Отмена</button>
      </div>
    </>);
  }

  if (props.moveMode) {
    const delta = parseMillimeters(moveValue);
    const update = (axis: TransformAxis, raw: string) => props.onMovePreview(axis, parseMillimeters(raw) ?? 0);
    return frame(<>
      <div className="selection-coach-copy">
        <span className="selection-coach-kind">Перемещение тела</span>
        <strong>{props.selectedPartName ?? "Сначала выберите тело"}</strong>
        <span>{props.movePreview
          ? `Смещение ${props.movePreview.axis.toUpperCase()}: ${formatNumber(props.movePreview.delta)} мм.`
          : "Потяните цветную стрелку или задайте ось и точное смещение. Плюс и минус задают направление."}</span>
      </div>
      <div className="selection-coach-actions">
        <select aria-label="Ось перемещения" value={moveAxis} onChange={(event) => {
          const axis = event.target.value as TransformAxis;
          setMoveAxis(axis); update(axis, moveValue);
        }}>
          <option value="x">X — красная</option><option value="y">Y — зелёная</option><option value="z">Z — синяя</option>
        </select>
        <label className="selection-size"><span>Смещение</span>
          <input aria-label="Смещение тела, мм" inputMode="decimal" value={moveValue}
            onChange={(event) => { setMoveValue(event.target.value); update(moveAxis, event.target.value); }}
            onKeyDown={(event) => { if (event.key === "Enter" && delta != null && delta !== 0) props.onMoveExact(moveAxis, delta); }} /><span>мм</span>
        </label>
        <button className="btn btn-primary" disabled={!props.selectedPartId || delta == null || delta === 0} onClick={() => delta != null && props.onMoveExact(moveAxis, delta)}>Переместить</button>
        <button className="btn" onClick={props.onCancelMove}>Завершить перемещение</button>
      </div>
    </>);
  }

  const selectedEdge = props.edgeTool.selected;
  const pushValue = parseMillimeters(props.pushPull.value);
  const canPush = props.pushPull.target && pushValue != null && pushValue >= props.pushPull.target.minimum
    && Math.abs(pushValue - props.pushPull.target.current) > 1e-9;
  const splitValue = parseMillimeters(splitOffset);
  const readyBoolean = targetId !== toolId && props.parts.some((part) => part.part_id === targetId)
    && props.parts.some((part) => part.part_id === toolId);

  return frame(<>
    <div className="selection-coach-copy">
      <span className="selection-coach-kind">{selectedEdge ? "Выбрано ребро" : props.selectedFace != null ? "Выбрана грань"
        : props.selectedPartIds.length > 1 ? `Выбрано тел: ${props.selectedPartIds.length}` : "Следующий шаг"}</span>
      <strong>{props.selectedPartName ?? "Выберите область модели"}</strong>
      <span>{selectedEdge ? `Длина ребра ${formatNumber(selectedEdge.length)} мм. Можно скруглить или снять фаску.`
        : props.pushPull.target ? "Потяните оранжевую стрелку или введите смещение грани. Плюс — наружу, минус — внутрь."
          : props.selectedFace != null ? `${props.faceArea != null ? `Площадь ${formatNumber(props.faceArea)} мм². ` : ""}${props.pushPull.reason ?? "Выберите действие."}`
            : "Нажмите на грань или ребро. Shift + клик добавляет или убирает тело из выбора."}</span>
    </div>
    <div className="selection-coach-actions">
      {props.pushPull.target && <>
        <label className="selection-size"><span>{props.pushPull.target.mode === "offset" ? "Смещение грани" : props.pushPull.target.label}</span>
          <input aria-label={props.pushPull.target.mode === "offset" ? "Смещение грани, мм" : "Размер грани, мм"}
            inputMode="decimal" value={props.pushPull.value} onChange={(event) => props.onPushPullValue(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter" && canPush) props.onApplyPushPull(); }} /><span>мм</span>
        </label>
        <button className="btn btn-primary" disabled={!canPush} data-cmd="op.face_offset" onClick={props.onApplyPushPull}>Изменить грань</button>
        {canPush && <button className="btn" onClick={props.onCancelPushPull}>Сбросить</button>}
      </>}
      {props.selectedFace != null && props.canAddFaceFeature && <button className="btn" onClick={props.onShowFaceActions}>Отверстие / выпуклость</button>}
      {props.selectedPartId && props.canResizeBody && <button className="btn btn-primary" data-cmd="op.resize_body" onClick={props.onStartBodyResize}>Изменить форму мышью</button>}
      {props.selectedPartId && <button className="btn" onClick={props.onStartMove}>Переместить тело</button>}
      {(selectedEdge || props.selectedFace == null) && edgeButtons}
      {props.selectedPartId && <button className={`btn ${splitOpen ? "btn-primary" : ""}`} onClick={() => {
        const open = !splitOpen;
        setSplitOpen(open); setSplitOffset(String(props.splitDefaults[splitPlane]));
        props.onSplitPreview(open ? splitPlane : null, props.splitDefaults[splitPlane]);
      }}>Разделить тело</button>}
      {props.parts.length > 1 && <button className={`btn ${booleanOpen ? "btn-primary" : ""}`} onClick={() => setBooleanOpen(!booleanOpen)}>Объединить / вычесть</button>}
      {splitOpen && <div className="selection-split" role="group" aria-label="Плоскость разделения">
        <select value={splitPlane} aria-label="Плоскость разделения" onChange={(event) => {
          const plane = event.target.value as SplitPlane;
          setSplitPlane(plane); setSplitOffset(String(props.splitDefaults[plane]));
          props.onSplitPreview(plane, props.splitDefaults[plane]);
        }}>
          <option value="YZ">По X (плоскость YZ)</option><option value="XZ">По Y (плоскость XZ)</option><option value="XY">По Z (плоскость XY)</option>
        </select>
        <label className="selection-size"><span>Положение</span>
          <input inputMode="decimal" value={splitOffset} aria-label="Положение плоскости разделения, мм" onChange={(event) => {
            setSplitOffset(event.target.value);
            const value = parseMillimeters(event.target.value);
            props.onSplitPreview(value == null ? null : splitPlane, value ?? undefined);
          }} /><span>мм</span>
        </label>
        <button className="btn btn-primary" disabled={splitValue == null} onClick={() => {
          if (splitValue != null) { props.onSplitPreview(null); props.onSplit(splitPlane, splitValue); }
        }}>Разделить</button>
        <button className="btn" onClick={() => { setSplitOpen(false); props.onSplitPreview(null); }}>Отмена разделения</button>
      </div>}
      {booleanOpen && <div className="selection-boolean" role="group" aria-label="Выбор тел для операции">
        <label>Изменяемое тело<select aria-label="Изменяемое тело" value={targetId} onChange={(event) => setTargetId(event.target.value)}>
          <option value="" disabled>Выберите тело</option>
          {props.parts.map((part) => <option key={part.part_id} value={part.part_id}>{part.name}</option>)}
        </select></label>
        <label>Второе тело<select aria-label="Тело-инструмент" value={toolId} onChange={(event) => setToolId(event.target.value)}>
          <option value="" disabled>Выберите тело</option>
          {props.parts.map((part) => <option key={part.part_id} value={part.part_id} disabled={part.part_id === targetId}>{part.name}</option>)}
        </select></label>
        <label>Действие<select aria-label="Действие с телами" value={booleanKind} onChange={(event) => setBooleanKind(event.target.value as BooleanKind)}>
          <option value="union">Объединить оба тела</option><option value="subtract">Вычесть второе из изменяемого</option><option value="intersect">Оставить общее пересечение</option>
        </select></label>
        <label className="selection-keep-tool"><input type="checkbox" checked={keepTool} onChange={(event) => setKeepTool(event.target.checked)} />Сохранить второе тело</label>
        <span className="selection-operation-hint">{booleanKind === "subtract" ? "Материал второго тела будет удалён из изменяемого."
          : booleanKind === "intersect" ? "Останется только общая часть двух тел." : "Два выбранных тела станут одной деталью."}</span>
        <button className="btn btn-primary" disabled={!readyBoolean} onClick={() => props.onBoolean(booleanKind, targetId, toolId, keepTool)}>Применить к двум телам</button>
      </div>}
    </div>
  </>);
}
