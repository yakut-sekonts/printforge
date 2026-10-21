import React from "react";
import type { CommandDef, DocState } from "./types";
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
  const get = (id: string) => commands.find((c) => c.command_id === id)!;
  return (
    <header className="topbar">
      <div className="brand">
        <svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" strokeWidth="1.5" aria-hidden>
          <rect x="1.5" y="3.5" width="13" height="9" rx="1.5" />
          <circle cx="5" cy="8" r="1.4" /><circle cx="11" cy="8" r="1.4" />
        </svg>
        <span className="brand-name">PrintForge</span>
        <span className="doc-name">
          {docName}
          {doc?.dirty && <span className="dirty-mark" title="Есть несохранённые изменения"> — изменено</span>}
        </span>
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

export function LeftPanel({ doc }: { doc: DocState | null }) {
  const p = doc?.params;
  return (
    <aside className="left-panel" aria-label="Детали и история">
      <section>
        <h2 className="panel-section">Детали</h2>
        {doc?.stats?.is_valid ? (
          <div className="part-card" data-cmd="part.plate" aria-label="Деталь «Пластина»">
            <div className="part-name"><IconPlate /> Пластина</div>
            <div className="part-params">
              {p ? `${fmt(p.length)} × ${fmt(p.width)} × ${fmt(p.height)} мм, Ø${fmt(p.hole_diameter)}, отступ ${fmt(p.hole_offset)}` : ""}
            </div>
          </div>
        ) : (
          <p className="panel-empty">Нет деталей.</p>
        )}
      </section>
      <section>
        <h2 className="panel-section">История операций</h2>
        {doc ? (
          <ol className="history-list">
            {Array.from({ length: doc.revision }, (_, i) => doc.revision - i).map((rev) => (
              <li key={rev} className={rev === doc.revision ? "history-current" : ""}>
                Ревизия {rev}{rev === doc.revision && <span className="history-badge">текущая</span>}
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

export function EmptyState({ onCreate, onLesson }: { onCreate: () => void; onLesson: () => void }) {
  return (
    <div className="empty-state">
      <IconBook />
      <h2>Создайте первую деталь</h2>
      <p>Начните с пластины из шаблона — задайте размеры в панели справа.</p>
      <div className="empty-actions">
        <button className="btn btn-primary" data-cmd="part.create.plate" aria-label="Создать пластину" onClick={onCreate}>
          <IconPlate /> Создать пластину
        </button>
        <button className="link-btn" onClick={onLesson}>Пройти урок «Первая деталь»</button>
      </div>
    </div>
  );
}
