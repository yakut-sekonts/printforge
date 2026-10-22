import React from "react";
import type { CommandDef, DocState, TemplateDef, DocStats } from "./types";
import {
  IconPlate, IconUndo, IconRedo, IconSave, IconOpen, IconExport,
  IconQuestion, IconCursorQuestion, IconBook,
} from "./icons";

export function cmdEnabled(c: CommandDef, doc: DocState | null): boolean {
  switch (c.availability) {
    case "always": return true;
    case "requires_document": return doc !== null;
    case "requires_body": return !!doc?.stats?.is_valid;
    case "requires_undo": return !!doc?.can_undo;
    case "requires_redo": return !!doc?.can_redo;
  }
}

interface TopBarProps {
  commands: CommandDef[];
  doc: DocState | null;
  docName: string;
  onCommand: (id: string) => void;
}

const TOPBAR_IDS = [
  "part.create.plate", "op.undo", "op.redo", "doc.save", "doc.open", "export.stl",
];
const TOPBAR_ICONS: Record<string, React.ReactNode> = {
  "part.create.plate": <IconPlate />,
  "op.undo": <IconUndo />,
  "op.redo": <IconRedo />,
  "doc.save": <IconSave />,
  "doc.open": <IconOpen />,
  "export.stl": <IconExport />,
};

export function TopBar({ commands, doc, docName, onCommand }: TopBarProps) {
  const get = (id: string) => commands.find((c) => c.command_id === id);
  return (
    <header className="topbar">
      <div className="brand">
        <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" strokeWidth="1.5" aria-hidden>
          <rect x="1.5" y="3.5" width="13" height="9" rx="1.5" />
          <circle cx="5" cy="8" r="1.4" /><circle cx="11" cy="8" r="1.4" />
        </svg>
        <span className="brand-name">PrintForge</span>
        <h1 className="doc-name">
          {docName}
          {doc?.dirty && <span className="dirty-mark" title="Есть несохранённые изменения"> — изменено</span>}
        </h1>
      </div>
      <nav className="topbar-actions" aria-label="Основные действия">
        {TOPBAR_IDS.map((id) => {
          const c = get(id);
          if (!c) return null;
          const enabled = cmdEnabled(c, doc);
          const title = !enabled && c.disabled_reason ? `${c.title} — ${c.disabled_reason}` : c.title;
          return (
            <button
              key={id}
              className="btn"
              data-cmd={id}
              aria-label={c.title}
              title={title}
              disabled={!enabled}
              onClick={() => onCommand(id)}
            >
              {TOPBAR_ICONS[id]}
              <span>{c.title}</span>
              {c.shortcut && <kbd>{c.shortcut.replace("CmdOrCtrl", "⌘").replace("Shift", "⇧").replaceAll("+", "")}</kbd>}
            </button>
          );
        })}
        <span className="topbar-sep" aria-hidden />
        <button className="btn" data-cmd="app.help.what_is_this" aria-label="Что это?" title="Что это? (Shift+Escape)" onClick={() => onCommand("app.help.what_is_this")}>
          <IconCursorQuestion />
          <span>Что это?</span>
        </button>
        <button className="btn icon-only" data-cmd="app.help.open" aria-label="Открыть справочник (⌘/)" title="Справочник (⌘/)" onClick={() => onCommand("app.help.open")}>
          <IconQuestion />
        </button>
      </nav>
    </header>
  );
}

interface LeftPanelProps {
  doc: DocState | null;
  templates: TemplateDef[];
  importedStats: DocStats | null;
  selectedPartId: string | null;
  onSelectPart: (partId: string) => void;
  onCreateTemplate: (t: TemplateDef) => void;
}

const TEMPLATE_BLURBS: Record<string, string> = {
  plate_with_holes: "Прямоугольная пластина с четырьмя отверстиями по углам.",
  washer: "Кольцевая шайба или втулка по диаметрам и высоте.",
  bracket_l: "Г-образный кронштейн: полка и стойка.",
  case_with_lid: "Корпус со съёмной крышкой и регулируемым зазором.",
};

export function LeftPanel({ doc, templates, importedStats, selectedPartId, onSelectPart, onCreateTemplate }: LeftPanelProps) {
  const p = doc?.params;
  const s = doc?.stats;
  const liveParts = s?.parts;
  const template = templates.find((t) => t.template_id === doc?.template);
  const isCase = doc?.template === "case_with_lid";
  return (
    <aside className="left-panel" aria-label="Детали и история">
      <section>
        <h2 className="panel-section">Создать</h2>
        <ul className="template-list">
          {templates.map((t) => (
            <li key={t.template_id}>
              <button
                className="template-row"
                data-cmd={t.command_id}
                aria-label={t.title}
                onClick={() => onCreateTemplate(t)}
              >
                <span className="template-title">{t.title}</span>
                <span className="template-blurb">{TEMPLATE_BLURBS[t.template_id] ?? ""}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="panel-section">Детали</h2>
        {liveParts && liveParts.length > 0 ? (
          <ul className="part-list">
            {liveParts.map((part) => (
              <li key={part.part_id}>
                <button
                  className={`part-row ${selectedPartId === part.part_id ? "part-selected" : ""}`}
                  data-cmd="part.select"
                  aria-label={`Деталь «${part.name}», объём ${fmt(part.volume)} мм³`}
                  onClick={() => onSelectPart(part.part_id)}
                >
                  <span className="part-row-name">{part.name}</span>
                  <span className="part-row-vol">{fmt(part.volume)} мм³</span>
                </button>
              </li>
            ))}
          </ul>
        ) : s?.is_valid && template ? (
          <div className="part-card" data-cmd={template.command_id} aria-label={`Деталь «${template.title}»`}>
            <div className="part-name"><IconPlate /> {template.title}</div>
            {isCase && s.case_volume != null && s.lid_volume != null ? (
              <div className="part-bodies">
                <div className="part-body-row">
                  <span>Корпус</span><span>{fmt(s.case_volume)} мм³</span>
                </div>
                <div className="part-body-row">
                  <span>Крышка</span><span>{fmt(s.lid_volume)} мм³</span>
                </div>
                {p?.gap != null && (
                  <div className="part-body-row">
                    <span>Зазор</span><span>{fmt(p.gap)} мм</span>
                  </div>
                )}
                {s.solid_count > 1 && <div className="part-body-row"><span>Тел: {s.solid_count}</span></div>}
              </div>
            ) : (
              <div className="part-params">
                {template.params.map((tp) => `${tp.label.toLowerCase()} ${fmt(p?.[tp.name])}`).join(", ")}
                {s.solid_count > 1 && <div>Тел: {s.solid_count}</div>}
              </div>
            )}
          </div>
        ) : importedStats ? null : (
          <p className="panel-empty">Нет деталей.</p>
        )}
        {importedStats && (
          <div className="part-card">
            <div className="part-name">Импортированная модель (сетка)</div>
            <div className="part-params">
              Треугольников: {importedStats.face_count}.
              Точные операции для сетки недоступны.
            </div>
          </div>
        )}
      </section>
      <section>
        <h2 className="panel-section">История операций</h2>
        {doc ? (
          <ol className="history-list">
            {Array.from({ length: doc.history_len ?? doc.revision }, (_, i) => (doc.history_len ?? doc.revision) - i).map((rev) => (
              <li key={rev} className={rev === (doc.history_index ?? doc.revision) + 1 ? "history-current" : ""}>
                Операция {rev}{rev === (doc.history_index ?? doc.revision) + 1 && <span className="history-badge">текущая</span>}
              </li>
            ))}
          </ol>
        ) : (
          <p className="panel-empty">История появится после первой операции.</p>
        )}
      </section>
    </aside>
  );
}

function fmt(v: number | undefined): string {
  if (v == null) return "—";
  return String(Math.round(v * 100) / 100);
}

interface StatusBarProps {
  doc: DocState | null;
  computing: boolean;
  message: string | null;
  selectedFace: number | null;
  faceArea: number | null;
}

export function StatusBar({ doc, computing, message, selectedFace, faceArea }: StatusBarProps) {
  const bbox = doc?.stats?.bbox;
  const dims = bbox
    ? `${fmt(bbox[3] - bbox[0])} × ${fmt(bbox[4] - bbox[1])} × ${fmt(bbox[5] - bbox[2])} мм`
    : null;
  return (
    <footer className="statusbar" aria-label="Строка состояния">
      <span className="status-item">мм</span>
      <span className="status-item">
        {selectedFace != null && faceArea != null
          ? `Грань ${selectedFace}: площадь ${fmt(faceArea)} мм²`
          : dims ? `Габариты: ${dims}` : "Нет детали"}
      </span>
      {message && <span className="status-item status-message">{message}</span>}
      <span className="status-spacer" />
      {computing && (
        <span className="status-item status-computing">
          <span className="spinner" aria-hidden /> Вычисление…
        </span>
      )}
      {doc?.error && <span className="status-item status-error">Ошибка геометрии</span>}
      {doc && <span className="status-item">Ревизия {doc.revision}</span>}
    </footer>
  );
}

export function EmptyState({ templates, onCreateTemplate, onLesson }: {
  templates: TemplateDef[];
  onCreateTemplate: (t: TemplateDef) => void;
  onLesson: () => void;
}) {
  return (
    <div className="empty-state">
      <IconBook />
      <h2>Создайте первую деталь</h2>
      <p>Выберите шаблон — размеры задаются в панели справа.</p>
      <ul className="empty-templates">
        {templates.map((t) => (
          <li key={t.template_id}>
            <button
              className="template-row"
              data-cmd={t.command_id}
              aria-label={t.title}
              onClick={() => onCreateTemplate(t)}
            >
              <span className="template-title">{t.title}</span>
              <span className="template-blurb">{TEMPLATE_BLURBS[t.template_id] ?? ""}</span>
            </button>
          </li>
        ))}
      </ul>
      <button className="link-btn" onClick={onLesson}>Пройти урок «Первая деталь»</button>
    </div>
  );
}
