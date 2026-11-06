import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CommandDef } from "./types";
import type { TooltipMode } from "./HelpPanel";
import { TooltipController } from "./tooltipController";

// Дополнительные описания для обучающих карточек (что делает / что выбрать / что изменится)
const TEACHING: Record<string, { does: string; select: string; changes: string }> = {
  "part.create.box": {
    does: "Создаёт точный параллелепипед с исходными размерами 40 × 30 × 20 мм.",
    select: "Ничего выбирать не нужно. После создания можно выбрать грань или ребро.",
    changes: "В документ добавится тело. Размеры доступны в Inspector, отмена — Cmd/Ctrl+Z.",
  },
  "part.create.cylinder": {
    does: "Добавляет точный цилиндр с редактируемыми диаметром и высотой.",
    select: "Ничего выбирать не нужно; затем выберите плоский торец или тело.",
    changes: "Появится новое тело. Криволинейную стенку нельзя смещать как плоскую грань.",
  },
  "part.create.sphere": {
    does: "Добавляет точную сферу с редактируемым диаметром.",
    select: "Ничего выбирать не нужно; для перемещения выберите тело.",
    changes: "Появится новое тело. Смещение криволинейной поверхности не поддерживается.",
  },
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
  anchor: HTMLElement;
}

export function Tooltips({ mode, commands, onOpenArticle }: Props) {
  const [tip, setTip] = useState<TipState | null>(null);
  const [position, setPosition] = useState({ left: 8, top: 8 });
  const tipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const openKeyboardHelp = (event: KeyboardEvent): boolean => {
      if (event.key !== "F1") return false;
      const element = event.target instanceof Element ? event.target.closest<HTMLElement>("[data-cmd]") : null;
      const command = commands.find((candidate) => candidate.command_id === element?.dataset.cmd);
      if (!command) return false;
      event.preventDefault();
      onOpenArticle(command.help_id);
      return true;
    };
    if (mode === "off") {
      setTip(null);
      document.addEventListener("keydown", openKeyboardHelp);
      return () => document.removeEventListener("keydown", openKeyboardHelp);
    }
    let anchor: HTMLElement | null = null;
    const controller = new TooltipController<HTMLElement>(mode === "teaching" ? 500 : 350, (target) => {
      const command = target && commands.find((candidate) => candidate.command_id === target.dataset.cmd);
      if (target && command && target.isConnected) {
        if (anchor && anchor !== target) {
          const descriptions = (anchor.getAttribute("aria-describedby") ?? "").split(/\s+/).filter((description) => description && description !== "printforge-tooltip");
          if (descriptions.length) anchor.setAttribute("aria-describedby", descriptions.join(" "));
          else anchor.removeAttribute("aria-describedby");
        }
        anchor = target;
        const descriptions = (target.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);
        if (!descriptions.includes("printforge-tooltip")) target.setAttribute("aria-describedby", [...descriptions, "printforge-tooltip"].join(" "));
        setTip({ cmd: command, anchor: target });
      } else {
        if (anchor) {
          const descriptions = (anchor.getAttribute("aria-describedby") ?? "").split(/\s+/).filter((description) => description && description !== "printforge-tooltip");
          if (descriptions.length) anchor.setAttribute("aria-describedby", descriptions.join(" "));
          else anchor.removeAttribute("aria-describedby");
        }
        anchor = null;
        setTip(null);
      }
    });
    const insideTip = (target: EventTarget | null) => target instanceof Node && !!tipRef.current?.contains(target);
    const inspectTarget = (target: EventTarget | null, keyboard: boolean) => {
      if (insideTip(target)) { controller.keepOpen(); return; }
      const element = target instanceof Element ? target.closest<HTMLElement>("[data-cmd]") : null;
      if (!element || !commands.some((command) => command.command_id === element.dataset.cmd)) { controller.hideSoon(); return; }
      controller.show(element, keyboard);
    };
    const onOver = (event: MouseEvent) => inspectTarget(event.target, false);
    const onFocus = (event: FocusEvent) => inspectTarget(event.target, true);
    const onOut = (event: MouseEvent | FocusEvent) => {
      if (insideTip(event.relatedTarget) || event.relatedTarget instanceof Node && anchor?.contains(event.relatedTarget)) controller.keepOpen();
      else controller.hideSoon();
    };
    const onDown = (event: MouseEvent) => { if (!insideTip(event.target)) controller.hide(); };
    const onKey = (event: KeyboardEvent) => {
      if (openKeyboardHelp(event)) controller.hide();
      else if (event.key !== "Tab" && !insideTip(event.target)) controller.hide();
      else if (event.key === "Escape") controller.hide();
    };
    const onResize = () => controller.hide();
    document.addEventListener("mouseover", onOver);
    document.addEventListener("mouseout", onOut);
    document.addEventListener("focusin", onFocus);
    document.addEventListener("focusout", onOut);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      controller.dispose();
      document.removeEventListener("mouseover", onOver);
      document.removeEventListener("mouseout", onOut);
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("focusout", onOut);
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, [mode, commands, onOpenArticle]);

  useLayoutEffect(() => {
    if (!tip || !tipRef.current) return;
    const anchor = tip.anchor.getBoundingClientRect();
    const bounds = tipRef.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(window.innerWidth - bounds.width - 8, anchor.left + anchor.width / 2 - bounds.width / 2));
    const below = anchor.bottom + 8;
    const top = Math.max(8, Math.min(window.innerHeight - bounds.height - 8, below + bounds.height <= window.innerHeight - 8 ? below : anchor.top - bounds.height - 8));
    setPosition({ left, top });
  }, [tip, mode]);

  if (!tip || mode === "off") return null;
  const teaching = TEACHING[tip.cmd.command_id];
  const style: React.CSSProperties = position;

  if (mode === "brief") {
    return (
      <div ref={tipRef} id="printforge-tooltip" className="tooltip tooltip-brief" style={style} role="tooltip">
        <strong>{tip.cmd.title}</strong>
        {teaching ? ` — ${teaching.does.replace(/\.$/, "").toLowerCase()}` : ""}
        {tip.cmd.shortcut && <kbd>{tip.cmd.shortcut.replace("CmdOrCtrl", "⌘").replace("Shift", "⇧").replaceAll("+", "")}</kbd>}
      </div>
    );
  }

  return (
    <div ref={tipRef} id="printforge-tooltip" className="tooltip tooltip-teaching" style={style} role="tooltip">
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
        <>
          <p><span className="tooltip-label">Что делает:</span> {tip.cmd.title}.</p>
          <p><span className="tooltip-label">Что выбрать:</span> Условия выбора и настройки описаны в статье команды.</p>
          <p><span className="tooltip-label">Что изменится:</span> Откройте статью перед применением, чтобы проверить результат и способ отмены.</p>
        </>
      )}
      <button className="link-btn" onClick={() => onOpenArticle(tip.cmd.help_id)}>
        Открыть статью справки
      </button>
      <span className="tooltip-keyboard">F1 — открыть статью с клавиатуры</span>
    </div>
  );
}
