import React, { useEffect, useState } from "react";
import type { DocState, GeoError } from "./types";
import { evalExpression } from "./expr";

export interface ParamValues {
  length: string;
  width: string;
  height: string;
  hole_diameter: string;
  hole_offset: string;
}

export const PARAM_LABELS: Record<keyof ParamValues, string> = {
  length: "Длина",
  width: "Ширина",
  height: "Толщина",
  hole_diameter: "Диаметр отверстия",
  hole_offset: "Отступ от краёв",
};

const PARAM_ORDER: (keyof ParamValues)[] = ["length", "width", "height", "hole_diameter", "hole_offset"];
const PARAM_CMD: Record<keyof ParamValues, string> = {
  length: "parameter.set", width: "parameter.set", height: "parameter.set",
  hole_diameter: "op.hole.add", hole_offset: "op.hole.add",
};

interface Props {
  doc: DocState | null;
  selectedFace: number | null;
  faceArea: number | null;
  onApply: (values: ParamValues) => void;
  onUndoFromError: () => void;
  savePath: string; setSavePath: (v: string) => void;
  openPath: string; setOpenPath: (v: string) => void;
  exportPath: string; setExportPath: (v: string) => void;
  onSave: () => void; onOpen: () => void; onExport: () => void;
}

export function ParamsPanel(props: Props) {
  const { doc } = props;
  const [values, setValues] = useState<ParamValues>({
    length: "80", width: "40", height: "6", hole_diameter: "4", hole_offset: "10",
  });
  const [exprError, setExprError] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  useEffect(() => {
    if (!doc) return;
    setValues((prev) => {
      const next = { ...prev };
      for (const k of PARAM_ORDER) {
        const expr = doc.expressions?.[k];
        const v = doc.params?.[k];
        next[k] = expr ?? (v != null ? String(v) : prev[k]);
      }
      return next;
    });
  }, [doc]);

  const evaluateAll = (): Record<string, number> | null => {
    const vars: Record<string, number> = { ...(doc?.params ?? {}) };
    // сначала подставляем новые значения простых чисел, чтобы выражения видели их
    for (const k of PARAM_ORDER) {
      const raw = values[k].trim().replace(",", ".");
      if (/^-?\d+(\.\d+)?$/.test(raw)) vars[k] = Number(raw);
    }
    const out: Record<string, number> = {};
    for (const k of PARAM_ORDER) {
      const raw = values[k].trim();
      if (!raw) { setExprError(`Поле «${PARAM_LABELS[k]}» пустое`); return null; }
      try {
        const v = evalExpression(raw, vars);
        if (v <= 0) { setExprError(`«${PARAM_LABELS[k]}» должно быть больше нуля`); return null; }
        out[k] = v;
        vars[k] = v;
      } catch (e) {
        setExprError(`«${PARAM_LABELS[k]}»: ${e instanceof Error ? e.message : String(e)}`);
        return null;
      }
    }
    setExprError(null);
    return out;
  };

  const apply = () => {
    const nums = evaluateAll();
    if (!nums) return;
    props.onApply(values);
  };

  const computedHint = (k: keyof ParamValues): string | null => {
    const raw = values[k].trim();
    if (!raw || /^-?\d+([.,]\d+)?$/.test(raw)) return null;
    try {
      const vars: Record<string, number> = { ...(doc?.params ?? {}) };
      const v = evalExpression(raw, vars);
      return `= ${Math.round(v * 100) / 100} мм`;
    } catch {
      return "ошибка в выражении";
    }
  };

  const err: GeoError | null = doc?.error ?? null;

  return (
    <aside className="right-panel" aria-label="Параметры">
      <h2 className="panel-section">Параметры</h2>

      {err && (
        <div className="error-box" role="alert">
          <div className="error-title">Ошибка геометрии</div>
          <p>{err.message}</p>
          {err.detail && (
            <>
              <button className="link-btn" onClick={() => setDetailOpen(!detailOpen)}>
                {detailOpen ? "Скрыть подробности" : "Подробности"}
              </button>
              {detailOpen && <pre className="error-detail">{err.detail}</pre>}
            </>
          )}
          <button className="btn" data-cmd="op.undo" aria-label="Отменить изменение" onClick={props.onUndoFromError}>
            Отменить изменение
          </button>
        </div>
      )}

      <div className="params-form">
        {PARAM_ORDER.map((k) => (
          <div className="param-field" key={k}>
            <label htmlFor={`param-${k}`}>{PARAM_LABELS[k]}</label>
            <div className="param-input" data-cmd={PARAM_CMD[k]}>
              <input
                id={`param-${k}`}
                inputMode="decimal"
                value={values[k]}
                aria-label={`${PARAM_LABELS[k]}, мм`}
                onChange={(e) => setValues({ ...values, [k]: e.target.value })}
                onKeyDown={(e) => { if (e.key === "Enter") apply(); }}
              />
              <span className="param-unit">мм</span>
            </div>
            {computedHint(k) && <div className="param-hint">{computedHint(k)}</div>}
          </div>
        ))}
        {exprError && <div className="error-inline" role="alert">{exprError}</div>}
        <button className="btn btn-primary" data-cmd={doc ? "parameter.set" : "part.create.plate"} aria-label="Применить параметры" onClick={apply}>
          Применить
        </button>
      </div>

      {props.selectedFace != null && props.faceArea != null && (
        <section className="face-info">
          <h3 className="panel-section">Выбранная грань</h3>
          <p>Грань {props.selectedFace} — площадь <strong>{Math.round(props.faceArea * 100) / 100} мм²</strong></p>
        </section>
      )}

      <section className="io-forms">
        <h3 className="panel-section">Файл проекта</h3>
        <div className="io-row">
          <input value={props.savePath} aria-label="Путь сохранения проекта" onChange={(e) => props.setSavePath(e.target.value)} />
          <button className="btn" data-cmd="doc.save" aria-label="Сохранить проект" disabled={!doc} onClick={props.onSave}>Сохранить</button>
        </div>
        <div className="io-row">
          <input value={props.openPath} aria-label="Путь открытия проекта" onChange={(e) => props.setOpenPath(e.target.value)} />
          <button className="btn" data-cmd="doc.open" aria-label="Открыть проект" onClick={props.onOpen}>Открыть</button>
        </div>
        <h3 className="panel-section">Экспорт</h3>
        <div className="io-row">
          <input value={props.exportPath} aria-label="Путь экспорта STL" onChange={(e) => props.setExportPath(e.target.value)} />
          <button className="btn" data-cmd="export.stl" aria-label="Экспортировать STL" disabled={!doc?.stats?.is_valid} onClick={props.onExport}>
            Экспорт STL
          </button>
        </div>
      </section>
    </aside>
  );
}
