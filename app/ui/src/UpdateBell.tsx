import React, { useCallback, useEffect, useRef, useState } from "react";
import type { Update } from "@tauri-apps/plugin-updater";
import { isTauri } from "./backend";
import { IconBell } from "./icons";

type UpdatePhase =
  | "unavailable"
  | "idle"
  | "checking"
  | "current"
  | "available"
  | "downloading"
  | "ready"
  | "installing"
  | "error";

interface UpdateBellProps {
  hasUnsavedChanges: boolean;
}

function updateErrorMessage(error: unknown): string {
  console.error("Не удалось выполнить обновление PrintForge", error);
  return "Не удалось связаться с сервером обновлений. Проверьте интернет-соединение и повторите попытку.";
}

function formatReleaseDate(value?: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "long" }).format(date);
}

export function UpdateBell({ hasUnsavedChanges }: UpdateBellProps) {
  const desktop = isTauri();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<UpdatePhase>(desktop ? "idle" : "unavailable");
  const [currentVersion, setCurrentVersion] = useState<string | null>(null);
  const [availableVersion, setAvailableVersion] = useState<string | null>(null);
  const [releaseDate, setReleaseDate] = useState<string | null>(null);
  const [releaseNotes, setReleaseNotes] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const updateRef = useRef<Update | null>(null);

  const closeCurrentUpdate = useCallback(async () => {
    const current = updateRef.current;
    updateRef.current = null;
    if (current) await current.close().catch(() => {});
  }, []);

  const checkForUpdates = useCallback(async () => {
    if (!desktop) {
      setPhase("unavailable");
      return;
    }
    setPhase("checking");
    setMessage(null);
    setProgress(null);
    try {
      await closeCurrentUpdate();
      const [{ check }, { getVersion }] = await Promise.all([
        import("@tauri-apps/plugin-updater"),
        import("@tauri-apps/api/app"),
      ]);
      setCurrentVersion(await getVersion());
      const update = await check({ timeout: 15_000 });
      if (!update) {
        setAvailableVersion(null);
        setReleaseDate(null);
        setReleaseNotes(null);
        setPhase("current");
        return;
      }
      updateRef.current = update;
      setCurrentVersion(update.currentVersion);
      setAvailableVersion(update.version);
      setReleaseDate(formatReleaseDate(update.date));
      setReleaseNotes(update.body?.trim() || null);
      setPhase("available");
    } catch (error) {
      setMessage(updateErrorMessage(error));
      setPhase("error");
    }
  }, [closeCurrentUpdate, desktop]);

  const downloadUpdate = useCallback(async () => {
    const update = updateRef.current;
    if (!update) return;
    setPhase("downloading");
    setMessage(null);
    setProgress(0);
    let downloaded = 0;
    let contentLength: number | undefined;
    try {
      await update.download((event) => {
        if (event.event === "Started") {
          contentLength = event.data.contentLength;
          setProgress(contentLength ? 0 : null);
        } else if (event.event === "Progress") {
          downloaded += event.data.chunkLength;
          if (contentLength) setProgress(Math.min(100, Math.round((downloaded / contentLength) * 100)));
        } else {
          setProgress(100);
        }
      }, { timeout: 120_000 });
      setPhase("ready");
    } catch (error) {
      setMessage(updateErrorMessage(error));
      setPhase("available");
      setProgress(null);
    }
  }, []);

  const installUpdate = useCallback(async () => {
    const update = updateRef.current;
    if (!update) return;
    if (hasUnsavedChanges) {
      setMessage("Сохраните текущий документ перед установкой обновления.");
      return;
    }
    setPhase("installing");
    setMessage(null);
    try {
      await update.install({ restartAfterInstall: true });
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    } catch (error) {
      setMessage(updateErrorMessage(error));
      setPhase("ready");
    }
  }, [hasUnsavedChanges]);

  useEffect(() => {
    if (!desktop) return;
    const timer = window.setTimeout(() => void checkForUpdates(), 1_500);
    return () => window.clearTimeout(timer);
  }, [checkForUpdates, desktop]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  const updateAvailable = phase === "available" || phase === "downloading" || phase === "ready" || phase === "installing";
  const title = updateAvailable
    ? `Доступно обновление ${availableVersion ?? ""}`.trim()
    : "Обновления PrintForge";

  return (
    <div className="update-bell">
      <button
        className="btn icon-only update-bell-button"
        aria-label={title}
        aria-expanded={open}
        title={title}
        onClick={() => setOpen((value) => !value)}
      >
        <IconBell />
        {updateAvailable && <span className="update-badge" aria-hidden />}
      </button>
      {open && (
        <section className="update-popover" role="dialog" aria-label="Обновления PrintForge">
          <div className="update-heading">
            <div>
              <strong>Обновления</strong>
              {currentVersion && <span>Версия {currentVersion}</span>}
            </div>
            <button className="icon-btn" aria-label="Закрыть" onClick={() => setOpen(false)}>×</button>
          </div>

          {phase === "unavailable" && (
            <p className="update-copy">Проверка обновлений доступна только в установленном приложении для macOS или Windows.</p>
          )}
          {phase === "idle" && <p className="update-copy">Проверка ещё не выполнялась.</p>}
          {phase === "checking" && <p className="update-copy" aria-live="polite">Проверяем наличие новой версии…</p>}
          {phase === "current" && (
            <p className="update-copy update-positive">Установлена актуальная версия PrintForge.</p>
          )}
          {updateAvailable && (
            <div className="update-release">
              <strong>Доступна версия {availableVersion}</strong>
              {releaseDate && <span>{releaseDate}</span>}
              {releaseNotes && <p className="update-notes">{releaseNotes}</p>}
            </div>
          )}
          {phase === "downloading" && (
            <div className="update-progress" aria-live="polite">
              <progress max="100" value={progress ?? undefined} />
              <span>{progress == null ? "Скачиваем обновление…" : `Скачано ${progress}%`}</span>
            </div>
          )}
          {phase === "ready" && (
            <p className="update-copy update-positive">Обновление скачано и проверено. Для установки приложение перезапустится.</p>
          )}
          {phase === "installing" && <p className="update-copy" aria-live="polite">Устанавливаем обновление…</p>}
          {message && <p className="update-message" role="alert">{message}</p>}

          <div className="update-actions">
            {phase === "available" && (
              <button className="btn btn-primary" onClick={() => void downloadUpdate()}>Скачать обновление</button>
            )}
            {phase === "ready" && (
              <button className="btn btn-primary" onClick={() => void installUpdate()}>Установить и перезапустить</button>
            )}
            {(phase === "idle" || phase === "current" || phase === "error") && desktop && (
              <button className="btn" onClick={() => void checkForUpdates()}>Проверить обновления</button>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
