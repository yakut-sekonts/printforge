import React, { useEffect, useMemo, useState } from "react";
import type {
  DocState, GeoError, TemplateDef, EdgeRef, PrintCheck, ImportResult,
} from "./types";
import { evalExpression } from "./expr";

export interface FilletUi {
  active: boolean;
  selected: EdgeRef | null;
  radius: string;
}

interface Props {
  doc: DocState | null;
  templates: TemplateDef[];
  selectedFace: number | null;
  faceArea: number | null;
  selectedPartId: string | null;
  onApplyField: (name: string, raw: string, partId?: string) => void;
  // операции над деталями
  onAddPart: (t: TemplateDef) => void;
  onBoolean: (kind: "union" | "subtract" | "intersect", keepTool: boolean) => void;
  onArray: (count: number, step: [number, number, number]) => void;
  onMirror: (plane: "XY" | "XZ" | "YZ") => void;
  onSplit: (plane: "XY" | "XZ" | "YZ", offset: number) => void;
  onTransform: (translate: [number, number, number]) => void;
  // скругление
  fillet: FilletUi;
  onStartFillet: () => void;
  onSelectEdge: (e: EdgeRef) => void;
  onFilletRadius: (v: string) => void;
  onApplyFillet: () => void;
  onCancelFillet: () => void;
  onClearError: () => void;
  // проверка печати
  printChecks: PrintCheck[] | null;
  printBusy: boolean;
  onPrintCheck: (printer: { x: number; y: number; z: number }) => void;
  // импорт
  importPreview: ImportResult | null;
  importBusy: boolean;
  onImport: (path: string, format: "step" | "stl", unitScale?: number) => void;
  onCancelImportPreview: () => void;
  // файлы
  savePath: string; setSavePath: (v: string) => void;
  openPath: string; setOpenPath: (v: string) => void;
  exportPath: string; setExportPath: (v: string) => void;
  onSave: () => void; onOpen: () => void;
  onExport: (format: "stl" | "step" | "3mf") => void;
}

const PRINTER_KEY = "pf-printer";

function loadPrinter(): { x: string; y: string; z: string } {
  try {
    const raw = localStorage.getItem(PRINTER_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* игнор */ }
  return { x: "220", y: "220", z: "250" };
}

function fmtNum(v: number): string {
  return String(Math.round(v * 100) / 100);
}

function sameEdge(a: EdgeRef, b: EdgeRef): boolean {
  return a.kind === b.kind && a.solid_index === b.solid_index &&
    a.midpoint.every((v, i) => Math.abs(v - b.midpoint[i]) < 1e-6);
}

export function ParamsPanel(props: Props) {
  const { doc, templates, selectedPartId } = props;
  // активная деталь: выбранная или первая
  const activePart = doc?.parts?.find((p) => p.part_id === selectedPartId) ?? doc?.parts?.[0] ?? null;
  const isFirstPart = !activePart || doc?.parts?.[0]?.part_id === activePart.part_id;
  const template = templates.find((t) => t.template_id === (activePart?.template ?? doc?.template)) ?? null;
  const paramSource: Record<string, number> = activePart?.params ?? doc?.params ?? {};
  const exprFor = (name: string, def: number): string => {
    if (isFirstPart && doc?.expressions?.[name]) return doc.expressions[name];
    const v = paramSource[name];
    return v != null ? String(v) : String(def);
  };
  const [values, setValues] = useState<Record<string, string>>({});
  const [exprError, setExprError] = useState<string | null>(null);
  const [multiHint, setMultiHint] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [printer, setPrinter] = useState(loadPrinter);
  const [importPath, setImportPath] = useState("~/model.step");
  const [importFormat, setImportFormat] = useState<"step" | "stl">("step");
  const [keepTool, setKeepTool] = useState(false);
  const [arrayCount, setArrayCount] = useState("2");
  const [arrayStep, setArrayStep] = useState({ x: "50", y: "0", z: "0" });
  const [mirrorPlane, setMirrorPlane] = useState<"XY" | "XZ" | "YZ">("YZ");
  const [splitPlane, setSplitPlane] = useState<"XY" | "XZ" | "YZ">("XY");
  const [splitOffset, setSplitOffset] = useState("0");
  const [translate, setTranslate] = useState({ x: "0", y: "0", z: "0" });

  // значения полей из активной детали
  useEffect(() => {
    if (!doc || !template) return;
    const next: Record<string, string> = {};
    for (const p of template.params) next[p.name] = exprFor(p.name, p.default);
    setValues(next);
    setMultiHint(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, template, selectedPartId]);

  const changedFields = useMemo(() => {
    if (!doc || !template) return [];
    return template.params.filter((p) => {
      const cur = exprFor(p.name, p.default);
      return (values[p.name] ?? cur).trim() !== cur;
    }).map((p) => p.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values, doc, template]);

  const applyOne = (name: string, raw: string) => {
    const vars: Record<string, number> = { ...paramSource };
    try {
      const v = evalExpression(raw.trim(), vars);
      if (v <= 0) { setExprError(`Значение должно быть больше нуля`); return; }
      setExprError(null);
      setMultiHint(false);
      props.onApplyField(name, raw.trim(), activePart?.part_id);
    } catch (e) {
      setExprError(e instanceof Error ? e.message : String(e));
    }
  };

  const applyButton = () => {
    if (changedFields.length === 1) {
      applyOne(changedFields[0], values[changedFields[0]]);
    } else if (changedFields.length > 1) {
      setMultiHint(true);
    }
  };

  const computedHint = (name: string): string | null => {
    const raw = (values[name] ?? "").trim();
    if (!raw || /^-?\d+([.,]\d+)?$/.test(raw)) return null;
    try {
      const v = evalExpression(raw, { ...paramSource });
      return `= ${fmtNum(v)} мм`;
    } catch {
      return "ошибка в выражении";
    }
  };

  const liveParts = doc?.stats?.parts ?? [];
  const targetPart = liveParts.find((p) => p.part_id === selectedPartId) ?? liveParts[0] ?? null;
  const toolPart = targetPart
    ? liveParts[(liveParts.indexOf(targetPart) + 1) % liveParts.length] ?? null
    : null;
  const booleanReady = liveParts.length >= 2 && !!targetPart && !!toolPart;
  const num = (s: string) => Number(s.replace(",", ".")) || 0;

  const err: GeoError | null = doc?.error ?? null;
  const isFilletError = err?.code === "fillet_failed" || err?.code === "reselect_required";
  const edges = doc?.stats?.edges ?? [];
  const filletedEdges = (doc?.operations ?? [])
    .filter((o) => o.op === "fillet" && o.edge_ref)
    .map((o) => o.edge_ref!);

  const savePrinter = (p: { x: string; y: string; z: string }) => {
    setPrinter(p);
    localStorage.setItem(PRINTER_KEY, JSON.stringify(p));
  };

  const previewBbox = props.importPreview?.stats?.bbox;

  return (
    <aside className="right-panel" aria-label="Параметры и инструменты">
      <h2 className="panel-section">
        Параметры{template ? ` — ${template.title}` : ""}{activePart && liveParts.length > 1 ? ` (${activePart.name})` : ""}
      </h2>

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
          {isFilletError ? (
            <button className="btn" data-cmd="error.close" aria-label="Закрыть ошибку" onClick={props.onClearError}>
              Закрыть
            </button>
          ) : (
            <button className="btn" data-cmd="op.undo" aria-label="Отменить изменение" onClick={props.onClearError}>
              Отменить изменение
            </button>
          )}
        </div>
      )}

      {doc && template ? (
        <div className="params-form">
          {template.params.map((p) => (
            <div className="param-field" key={p.name}>
              <label htmlFor={`param-${p.name}`}>{p.label}</label>
              <div className="param-input" data-cmd="parameter.set">
                <input
                  id={`param-${p.name}`}
                  inputMode="decimal"
                  value={values[p.name] ?? ""}
                  aria-label={`${p.label}, ${p.unit}`}
                  onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                  onKeyDown={(e) => { if (e.key === "Enter") applyOne(p.name, values[p.name] ?? ""); }}
                />
                <span className="param-unit">
                  {p.name === "gap" ? "мм, на одну сторону" : p.unit}
                </span>
              </div>
              {computedHint(p.name) && <div className="param-hint">{computedHint(p.name)}</div>}
            </div>
          ))}
          {exprError && <div className="error-inline" role="alert">{exprError}</div>}
          {multiHint && <div className="param-hint">Изменено несколько полей — применяйте каждое поле клавишей Enter.</div>}
          <button
            className="btn btn-primary"
            data-cmd="parameter.set"
            aria-label="Применить параметр"
            disabled={changedFields.length !== 1}
            onClick={applyButton}
          >
            Применить
          </button>
        </div>
      ) : (
        <p className="panel-empty">Выберите шаблон слева, чтобы создать деталь.</p>
      )}

      {props.selectedFace != null && props.faceArea != null && (
        <section className="face-info">
          <h3 className="panel-section">Выбранная грань</h3>
          <p>Грань {props.selectedFace} — площадь <strong>{fmtNum(props.faceArea)} мм²</strong></p>
        </section>
      )}

      <section className="tool-section">
        <h3 className="panel-section">Скругление</h3>
        {!props.fillet.active ? (
          <button
            className="btn" data-cmd="op.fillet" aria-label="Скруглить ребро"
            disabled={!doc?.stats?.is_valid || !!doc?.error}
            onClick={props.onStartFillet}
          >
            Скруглить
          </button>
        ) : (
          <div className="fillet-panel">
            {edges.length === 0 && <p className="panel-empty">Рёбра не найдены.</p>}
            <ul className="edge-list">
              {edges.map((e, i) => {
                const done = filletedEdges.some((f) => sameEdge(f, e));
                const sel = props.fillet.selected && sameEdge(props.fillet.selected, e);
                return (
                  <li key={i}>
                    <button
                      className={`edge-row ${sel ? "edge-selected" : ""}`}
                      data-cmd="op.fillet"
                      aria-label={`Ребро ${e.kind}, длина ${fmtNum(e.length)} мм${done ? ", уже скруглено" : ""}`}
                      onClick={() => props.onSelectEdge(e)}
                    >
                      <span className="edge-kind">{e.kind}</span>
                      <span className="edge-len">{fmtNum(e.length)} мм</span>
                      <span className="edge-mid">
                        ({e.midpoint.map((v) => fmtNum(v)).join("; ")})
                      </span>
                      {done && <span className="history-badge">скруглено</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="param-field">
              <label htmlFor="fillet-radius">Радиус</label>
              <div className="param-input">
                <input
                  id="fillet-radius" inputMode="decimal"
                  value={props.fillet.radius}
                  aria-label="Радиус скругления, мм"
                  onChange={(e) => props.onFilletRadius(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") props.onApplyFillet(); }}
                />
                <span className="param-unit">мм</span>
              </div>
            </div>
            <div className="fillet-actions">
              <button
                className="btn btn-primary" data-cmd="op.fillet"
                aria-label="Применить скругление"
                disabled={!props.fillet.selected}
                onClick={props.onApplyFillet}
              >
                Применить скругление
              </button>
              <button className="btn" aria-label="Отменить выбор ребра" onClick={props.onCancelFillet}>Отмена</button>
            </div>
          </div>
        )}
      </section>

      <section className="tool-section">
        <h3 className="panel-section">Операции</h3>
        <details className="add-part">
          <summary className="btn" data-cmd="part.add" aria-label="Добавить деталь">Добавить деталь</summary>
          <ul className="template-list add-part-menu">
            {templates.map((t) => (
              <li key={t.template_id}>
                <button className="template-row" data-cmd="part.add" aria-label={`Добавить: ${t.title}`} onClick={() => props.onAddPart(t)}>
                  <span className="template-title">{t.title}</span>
                </button>
              </li>
            ))}
          </ul>
        </details>

        <div className="op-block">
          <div className="op-row">
            {([["union", "Объединить"], ["subtract", "Вычесть"], ["intersect", "Пересечь"]] as const).map(([kind, label]) => (
              <button
                key={kind} className="btn" data-cmd={`op.${kind}`}
                aria-label={label}
                disabled={!booleanReady}
                title={booleanReady ? label : "Сначала добавьте вторую деталь"}
                onClick={() => props.onBoolean(kind, keepTool)}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="keep-tool">
            <input type="checkbox" checked={keepTool} onChange={(e) => setKeepTool(e.target.checked)} />
            Сохранить инструмент
          </label>
          {booleanReady && targetPart && toolPart && (
            <p className="op-pair">Основное: {targetPart.name} · Инструмент: {toolPart.name}</p>
          )}
        </div>

        <div className="op-block">
          <span className="op-label">Массив</span>
          <div className="op-row">
            <div className="param-input op-field">
              <input inputMode="numeric" value={arrayCount} aria-label="Количество копий" onChange={(e) => setArrayCount(e.target.value)} />
              <span className="param-unit">шт</span>
            </div>
            {(["x", "y", "z"] as const).map((a) => (
              <div className="param-input op-field" key={a}>
                <input inputMode="decimal" value={arrayStep[a]} aria-label={`Шаг ${a.toUpperCase()}, мм`} onChange={(e) => setArrayStep({ ...arrayStep, [a]: e.target.value })} />
                <span className="param-unit">{a.toUpperCase()}</span>
              </div>
            ))}
          </div>
          <button
            className="btn" data-cmd="op.array" aria-label="Создать массив"
            disabled={!targetPart || parseInt(arrayCount, 10) < 2}
            title={!targetPart ? "Сначала создайте деталь" : parseInt(arrayCount, 10) < 2 ? "Количество — не меньше 2" : "Создать массив"}
            onClick={() => props.onArray(parseInt(arrayCount, 10), [num(arrayStep.x), num(arrayStep.y), num(arrayStep.z)])}
          >
            Массив
          </button>
        </div>

        <div className="op-block">
          <span className="op-label">Зеркало</span>
          <div className="op-row">
            <select value={mirrorPlane} aria-label="Плоскость зеркала" onChange={(e) => setMirrorPlane(e.target.value as "XY" | "XZ" | "YZ")}>
              <option value="XY">XY</option><option value="XZ">XZ</option><option value="YZ">YZ</option>
            </select>
            <button
              className="btn" data-cmd="op.mirror" aria-label="Зеркалировать деталь"
              disabled={!targetPart} title={!targetPart ? "Сначала создайте деталь" : "Зеркалировать"}
              onClick={() => props.onMirror(mirrorPlane)}
            >
              Зеркало
            </button>
          </div>
        </div>

        <div className="op-block">
          <span className="op-label">Разделить деталь</span>
          <div className="op-row">
            <select value={splitPlane} aria-label="Плоскость разреза" onChange={(e) => setSplitPlane(e.target.value as "XY" | "XZ" | "YZ")}>
              <option value="XY">XY</option><option value="XZ">XZ</option><option value="YZ">YZ</option>
            </select>
            <div className="param-input op-field">
              <input inputMode="decimal" value={splitOffset} aria-label="Смещение плоскости, мм" onChange={(e) => setSplitOffset(e.target.value)} />
              <span className="param-unit">мм</span>
            </div>
            <button
              className="btn" data-cmd="op.split" aria-label="Разделить деталь"
              disabled={!targetPart} title={!targetPart ? "Сначала создайте деталь" : "Разделить деталь"}
              onClick={() => props.onSplit(splitPlane, num(splitOffset))}
            >
              Разделить
            </button>
          </div>
        </div>

        <div className="op-block">
          <span className="op-label">Переместить</span>
          <div className="op-row">
            {(["x", "y", "z"] as const).map((a) => (
              <div className="param-input op-field" key={a}>
                <input inputMode="decimal" value={translate[a]} aria-label={`Сдвиг ${a.toUpperCase()}, мм`} onChange={(e) => setTranslate({ ...translate, [a]: e.target.value })} />
                <span className="param-unit">{a.toUpperCase()}, мм</span>
              </div>
            ))}
            <button
              className="btn" data-cmd="op.transform" aria-label="Переместить деталь"
              disabled={!targetPart} title={!targetPart ? "Сначала создайте деталь" : "Переместить деталь"}
              onClick={() => props.onTransform([num(translate.x), num(translate.y), num(translate.z)])}
            >
              Переместить
            </button>
          </div>
        </div>
      </section>

      <section className="tool-section">
        <h3 className="panel-section">Проверка перед печатью</h3>
        <div className="printer-row">
          {(["x", "y", "z"] as const).map((axis) => (
            <div className="param-input printer-field" key={axis}>
              <input
                inputMode="decimal" value={printer[axis]}
                aria-label={`Габарит принтера ${axis.toUpperCase()}, мм`}
                onChange={(e) => savePrinter({ ...printer, [axis]: e.target.value })}
              />
              <span className="param-unit">{axis.toUpperCase()}, мм</span>
            </div>
          ))}
        </div>
        <button
          className="btn" data-cmd="check.print" aria-label="Проверить перед печатью"
          disabled={!doc?.stats?.is_valid || props.printBusy}
          onClick={() => props.onPrintCheck({
            x: Number(printer.x.replace(",", ".")) || 220,
            y: Number(printer.y.replace(",", ".")) || 220,
            z: Number(printer.z.replace(",", ".")) || 250,
          })}
        >
          {props.printBusy ? "Проверка…" : "Проверить"}
        </button>
        {props.printChecks && (
          <>
            <ul className="check-list">
              {props.printChecks.map((c) => (
                <li key={c.id} className={`check-row check-${c.status}`}>
                  <span className="check-status">
                    {c.status === "pass" ? "Пройдено" : c.status === "fail" ? "Ошибка" : "Не проверено"}
                  </span>
                  <span className="check-title">{c.title}</span>
                  {c.detail && <span className="check-detail">{c.detail}</span>}
                </li>
              ))}
            </ul>
            <p className="check-note">«Проверки пройдены» означает только перечисленные проверки.</p>
          </>
        )}
      </section>

      <section className="tool-section">
        <h3 className="panel-section">Импорт</h3>
        <div className="io-row">
          <input value={importPath} aria-label="Путь к импортируемой модели" onChange={(e) => setImportPath(e.target.value)} />
          <select
            value={importFormat} aria-label="Формат импорта"
            onChange={(e) => setImportFormat(e.target.value as "step" | "stl")}
          >
            <option value="step">STEP</option>
            <option value="stl">STL</option>
          </select>
        </div>
        {!props.importPreview ? (
          <button
            className="btn" data-cmd="io.import" aria-label="Импортировать модель"
            disabled={props.importBusy}
            onClick={() => props.onImport(importPath, importFormat, importFormat === "step" ? undefined : undefined)}
          >
            {props.importBusy ? "Импорт…" : "Импортировать"}
          </button>
        ) : (
          <div className="import-preview">
            {importFormat === "stl" && previewBbox ? (
              <>
                <p>
                  Габарит сетки: {fmtNum(previewBbox[3] - previewBbox[0])} × {fmtNum(previewBbox[4] - previewBbox[1])} × {fmtNum(previewBbox[5] - previewBbox[2])}.
                  Выберите единицы исходного файла:
                </p>
                <div className="fillet-actions">
                  <button className="btn btn-primary" data-cmd="io.import" aria-label="Единицы — миллиметры" onClick={() => props.onImport(importPath, "stl", 1)}>
                    мм (×1)
                  </button>
                  <button className="btn" data-cmd="io.import" aria-label="Единицы — дюймы" onClick={() => props.onImport(importPath, "stl", 25.4)}>
                    дюймы (×25,4)
                  </button>
                  <button className="btn" aria-label="Отменить импорт" onClick={props.onCancelImportPreview}>Отмена</button>
                </div>
              </>
            ) : (
              <p>Модель импортирована.</p>
            )}
          </div>
        )}
      </section>

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
          <input value={props.exportPath} aria-label="Путь экспорта" onChange={(e) => props.setExportPath(e.target.value)} />
        </div>
        <div className="export-formats">
          {(["stl", "step", "3mf"] as const).map((f) => (
            <button
              key={f} className="btn" data-cmd={`export.${f}`}
              aria-label={`Экспортировать ${f.toUpperCase()}`}
              disabled={!doc?.stats?.is_valid}
              onClick={() => props.onExport(f)}
            >
              {f.toUpperCase()}
            </button>
          ))}
        </div>
      </section>
    </aside>
  );
}
