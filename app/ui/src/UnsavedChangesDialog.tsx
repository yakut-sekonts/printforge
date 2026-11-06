import React, { useEffect, useRef } from "react";

interface Props {
  replacing: boolean;
  path: string;
  busy: boolean;
  error: string | null;
  onPath: (value: string) => void;
  onSave: () => void;
  onDiscard: () => void;
  onCancel: () => void;
}

export function UnsavedChangesDialog(props: Props) {
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    dialog.current?.querySelector<HTMLButtonElement>('[data-cancel]')?.focus();
    return () => { if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, []);
  return (
    <div className="close-dialog-backdrop">
      <section className="close-dialog" role="dialog" aria-modal="true" aria-labelledby="unsaved-title" ref={dialog}
        onKeyDown={(event) => {
          event.stopPropagation();
          if (event.key === "Escape") { event.preventDefault(); if (!props.busy) props.onCancel(); }
          if (event.key === "Tab") {
            const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)')];
            const index = controls.indexOf(document.activeElement as HTMLElement);
            if (event.shiftKey && index <= 0) { event.preventDefault(); controls[controls.length - 1]?.focus(); }
            else if (!event.shiftKey && index === controls.length - 1) { event.preventDefault(); controls[0]?.focus(); }
          }
        }}>
        <h2 id="unsaved-title">Сохранить изменения?</h2>
        <p>{props.replacing ? "Импорт STEP откроет новый документ. Текущая модель содержит несохранённые изменения." : "Текущий проект содержит несохранённые изменения. Сохраните их перед выходом."}</p>
        <label htmlFor="unsaved-save-path">Путь сохранения проекта</label>
        <input id="unsaved-save-path" aria-label="Путь сохранения перед выходом" value={props.path} disabled={props.busy} onChange={(event) => props.onPath(event.target.value)} />
        {props.error && <p className="error-inline" role="alert">{props.error}</p>}
        <div className="close-dialog-actions">
          <button className="btn btn-primary" disabled={props.busy || !props.path.trim()} onClick={props.onSave}>{props.busy ? "Сохранение…" : "Сохранить и продолжить"}</button>
          <button className="btn" disabled={props.busy} onClick={props.onDiscard}>Не сохранять</button>
          <button className="btn" data-cancel disabled={props.busy} onClick={props.onCancel}>Отмена</button>
        </div>
      </section>
    </div>
  );
}
