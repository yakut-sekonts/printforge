import React, { useEffect, useState } from "react";
import { backend, isTauri, parseIpcError } from "./backend";

export function RecoveryNotice({ busy, restore }: { busy: boolean; restore: (name: string) => Promise<boolean> }) {
  const [available, setAvailable] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState(false);
  const [working, setWorking] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  useEffect(() => {
    if (!isTauri()) return;
    let disposed = false;
    const load = async () => {
      try {
        const state = await backend.recoveryStatus();
        if (!disposed) { setAvailable(state.available); setError(state.error); }
      } catch (cause) { if (!disposed) setError(parseIpcError(cause).message); }
    };
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, []);
  if (hidden || !available.length && !error) return null;
  return <section className="recovery-notice" aria-label="Аварийное восстановление" role="status">
    <strong>{available.length ? "Есть recovery-копия предыдущей сессии" : "Recovery временно недоступен"}</strong>
    <p>{error ?? "Восстановление откроет отдельный несохранённый проект. Исходный файл не перезаписывается. Копия создаётся раз в 30 секунд; последние изменения перед сбоем могут отсутствовать."}</p>
    {!!available.length && <><button className="btn btn-primary" disabled={busy || working} onClick={async () => {
      setWorking(true);
      try { if (await restore(available[0])) { const state = await backend.recoveryStatus(); setAvailable(state.available); } }
      catch (cause) { setError(parseIpcError(cause).message); }
      finally { setWorking(false); }
    }}>Восстановить</button><button className="btn" disabled={busy || working} onClick={async () => {
      if (!confirmDiscard) { setConfirmDiscard(true); return; }
      setWorking(true);
      try { const state = await backend.recoveryDiscard(available[0]); setAvailable(state.available); setConfirmDiscard(false); }
      catch (cause) { setError(parseIpcError(cause).message); }
      finally { setWorking(false); }
    }}>{confirmDiscard ? "Подтвердить удаление копии" : "Удалить копию"}</button></>}
    <button className="btn" disabled={working} onClick={() => setHidden(true)}>Позже</button>
  </section>;
}
