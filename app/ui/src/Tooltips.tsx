import React, { useEffect, useState } from "react";
import type { CommandDef } from "./types";
import type { TooltipMode } from "./HelpPanel";

// Дополнительные описания для обучающих карточек (что делает / что выбрать / что изменится)
const TEACHING: Record<string, { does: string; select: string; changes: string }> = {
  "part.create.plate": {
    does: "Создаёт прямоугольную пластину с четырьмя отверстиями по размерам из панели параметров.",
    select: "Ничего выбирать не нужно — задайте длину, ширину и толщину справа.",
    changes: "На сцене появится новая деталь, история операций получит первую ревизию.",
  },
  "op.undo": {
    does: "Отменяет последнее изменение документа.",
    select: "Ничего выбирать не нужно.",
    changes: "Документ вернётся к предыдущей ревизии.",
  },
  "op.redo": {
    does: "Повторяет отменённое изменение.",
    select: "Ничего выбирать не нужно.",
    changes: "Документ перейдёт к следующей ревизии.",
  },
  "doc.save": {
    does: "Сохраняет проект в файл .printforge по указанному пути.",
    select: "Проверьте путь рядом с кнопкой.",
    changes: "Метка несохранённых изменений исчезнет.",
  },
  "doc.open": {
    does: "Открывает проект .printforge, заменяя текущий документ.",
    select: "Укажите путь к файлу.",
    changes: "Сцена и параметры загрузятся из файла.",
  },
  "export.stl": {
    does: "Экспортирует деталь в STL для слайсера.",
    select: "Проверьте путь экспорта.",
    changes: "Файл появится на диске; в статус-баре — размер и объём.",
  },
  "app.help.open": {
    does: "Открывает справочник в правой панели.",
    select: "Ничего выбирать не нужно.",
    changes: "Появится панель со статьями и уроками.",
  },
  "app.help.what_is_this": {
    does: "Включает режим «Что это?»: следующий клик по элементу откроет статью о нём.",
    select: "Кликните любую кнопку с командой.",
    changes: "Откроется справка по выбранному элементу.",
  },
};

interface Props {
  mode: TooltipMode;
  commands: CommandDef[];
  onOpenArticle: (helpId: string) => void;
}

interface TipState {
  cmd: CommandDef;
  x: number;
  y: number;
}

export function Tooltips({ mode, commands, onOpenArticle }: Props) {
  const [tip, setTip] = useState<TipState | null>(null);

  useEffect(() => {
    if (mode === "off") { setTip(null); return; }
    let timer: number | undefined;
    const onOver = (e: MouseEvent) => {
      const el = (e.target as HTMLElement).closest?.("[data-cmd]") as HTMLElement | null;
      if (!el) { setTip(null); return; }
      const cmd = commands.find((c) => c.command_id === el.dataset.cmd);
      if (!cmd) { setTip(null); return; }
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const r = el.getBoundingClientRect();
        setTip({ cmd, x: r.left + r.width / 2, y: r.bottom + 8 });
      }, mode === "teaching" ? 500 : 350);
    };
    const onLeave = () => { window.clearTimeout(timer); setTip(null); };
    document.addEventListener("mouseover", onOver);
    document.addEventListener("mousedown", onLeave);
    document.addEventListener("keydown", onLeave);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("mouseover", onOver);
      document.removeEventListener("mousedown", onLeave);
      document.removeEventListener("keydown", onLeave);
    };
  }, [mode, commands]);

  if (!tip || mode === "off") return null;
  const teaching = TEACHING[tip.cmd.command_id];
  const style: React.CSSProperties = {
    left: Math.max(8, Math.min(window.innerWidth - 340, tip.x - 160)),
    top: tip.y,
  };

  if (mode === "brief") {
    return (
      <div className="tooltip tooltip-brief" style={style} role="tooltip">
        <strong>{tip.cmd.title}</strong>
        {teaching ? ` — ${teaching.does.replace(/\.$/, "").toLowerCase()}` : ""}
        {tip.cmd.shortcut && <kbd>{tip.cmd.shortcut.replace("CmdOrCtrl", "⌘").replace("Shift", "⇧").replaceAll("+", "")}</kbd>}
      </div>
    );
  }

  return (
    <div className="tooltip tooltip-teaching" style={style} role="tooltip">
      <div className="tooltip-title">
        {tip.cmd.title}
        {tip.cmd.shortcut && <kbd>{tip.cmd.shortcut.replace("CmdOrCtrl", "⌘").replace("Shift", "⇧").replaceAll("+", "")}</kbd>}
      </div>
      {teaching ? (
        <>
          <p><span className="tooltip-label">Что делает:</span> {teaching.does}</p>
          <p><span className="tooltip-label">Что выбрать:</span> {teaching.select}</p>
          <p><span className="tooltip-label">Что изменится:</span> {teaching.changes}</p>
        </>
      ) : (
        <p>Команда интерфейса.</p>
      )}
      <button className="link-btn" onClick={() => onOpenArticle(tip.cmd.help_id)}>
        Открыть статью справки
      </button>
    </div>
  );
}
