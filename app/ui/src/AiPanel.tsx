import React, { useEffect, useRef, useState } from "react";
import type { AiOperation, AiPlanResponse, AiProviderInfo } from "./types";
import { backend, parseIpcError } from "./backend";
import { IconClose, IconSparkles } from "./icons";

const EXAMPLE_PROMPT = "Создай шайбу: наружный диаметр 20 мм, внутренний 6 мм, высота 4 мм";
const OLLAMA_DEFAULT_BASE = "http://127.0.0.1:11434/v1";

interface AiPanelProps {
  documentRevision: number;
  onClose: () => void;
  onApply: (
    operations: AiOperation[],
    baseRevision: number,
    documentInstanceId: string | number,
    planHash: string,
    actionId: string,
  ) => Promise<number | null>;
  onOpenHelp: () => void;
}

interface SettingsDraft {
  provider: AiProviderInfo["provider"];
  base_url: string;
  model: string;
}

const EMPTY_SETTINGS: SettingsDraft = { provider: "disabled", base_url: "", model: "" };

function formatNumber(value: number | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value);
}

function operationTitle(operation: AiOperation): string {
  switch (operation.command_id) {
    case "part.create.from_template": return "Создать деталь из шаблона";
    case "parameter.set": return "Изменить параметр";
    case "op.fillet": return "Добавить скругление";
  }
}

function operationDetail(operation: AiOperation): string {
  const parameters = operation.parameters;
  if (operation.command_id === "part.create.from_template") {
    const values = parameters.params as Record<string, unknown> | undefined;
    const summary = values
      ? Object.entries(values).map(([name, value]) => `${name}: ${String(value)}`).join(", ")
      : "";
    return `${String(parameters.template ?? "")}${summary ? ` — ${summary}` : ""}`;
  }
  if (operation.command_id === "parameter.set") {
    return `${String(parameters.name ?? "параметр")} → ${String(parameters.value ?? "—")} мм`;
  }
  return `Радиус ${String(parameters.radius ?? "—")} мм`;
}

function providerTitle(provider: AiProviderInfo | null): string {
  if (!provider) return "Определяем провайдера";
  switch (provider.provider) {
    case "disabled": return "AI выключен";
    case "ollama": return `Ollama · ${provider.model}`;
    case "openai": return `OpenAI-compatible · ${provider.model}`;
    case "scripted": return provider.model;
  }
}

function dataDisclosure(settings: SettingsDraft): string {
  switch (settings.provider) {
    case "disabled":
      return "AI-запросы не выполняются; данные документа никуда не отправляются.";
    case "scripted":
      return "Режим разработки работает локально без сети и не отправляет данные документа.";
    case "ollama":
      return "В локальный Ollama отправляются ваш запрос и компактное описание деталей: шаблоны, размеры и операции. Сетка, файл проекта и история не отправляются.";
    case "openai":
      return "На указанный endpoint отправляются ваш запрос и компактное описание деталей: шаблоны, размеры и операции. Сетка и файл проекта не отправляются. Обработка данных зависит от владельца endpoint.";
  }
}

export function AiPanel({ documentRevision, onClose, onApply, onOpenHelp }: AiPanelProps) {
  const [provider, setProvider] = useState<AiProviderInfo | null>(null);
  const [settings, setSettings] = useState<SettingsDraft>(EMPTY_SETTINGS);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [newApiKey, setNewApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [connectionBusy, setConnectionBusy] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsMessage, setSettingsMessage] = useState<string | null>(null);
  const [connectionWarning, setConnectionWarning] = useState(false);
  const [prompt, setPrompt] = useState(EXAMPLE_PROMPT);
  const [response, setResponse] = useState<AiPlanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  const [applying, setApplying] = useState(false);
  const [appliedRevision, setAppliedRevision] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let active = true;
    backend.aiProviders()
      .then((info) => {
        if (!active) return;
        setProvider(info);
        setSettings({ provider: info.provider, base_url: info.base_url, model: info.scripted ? "" : info.model });
        if (info.provider === "disabled") setSettingsOpen(true);
      })
      .catch((cause) => { if (active) setSettingsError(parseIpcError(cause).message); });
    return () => {
      active = false;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (appliedRevision == null || documentRevision === appliedRevision) return;
    setAppliedRevision(null);
    setResponse(null);
    setError("Документ изменился. Пересчитайте предложение перед применением.");
  }, [appliedRevision, documentRevision]);

  const saveSettings = async (testAfterSave: boolean) => {
    if (settings.provider === "scripted") return;
    setSettingsBusy(true);
    setSettingsError(null);
    setSettingsMessage(null);
    setConnectionWarning(false);
    try {
      const info = await backend.aiConfigure({
        provider: settings.provider,
        base_url: settings.base_url.trim(),
        model: settings.model.trim(),
        api_key: newApiKey || undefined,
        clear_api_key: clearApiKey || undefined,
      });
      setProvider(info);
      setSettings({ provider: info.provider, base_url: info.base_url, model: info.scripted ? "" : info.model });
      setNewApiKey("");
      setClearApiKey(false);
      setResponse(null);
      setAppliedRevision(null);
      setError(null);
      setSettingsMessage("Настройки сохранены.");
      if (testAfterSave && info.available) {
        setConnectionBusy(true);
        const result = await backend.aiTestConnection();
        setSettingsMessage(result.message);
        setConnectionWarning(!result.model_found);
      }
    } catch (cause) {
      setSettingsMessage(null);
      setSettingsError(parseIpcError(cause).message);
    } finally {
      setConnectionBusy(false);
      setSettingsBusy(false);
    }
  };

  const requestPlan = async () => {
    if (!prompt.trim()) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPlanning(true);
    setAppliedRevision(null);
    setError(null);
    setResponse(null);
    try {
      setResponse(await backend.aiPlan(prompt.trim(), controller.signal));
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === "AbortError")) {
        setError(parseIpcError(cause).message);
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setPlanning(false);
      }
    }
  };

  const applyPlan = async () => {
    if (!response?.plan.operations.length) return;
    setApplying(true);
    setError(null);
    try {
      const revision = await onApply(
        response.plan.operations,
        response.plan.base_revision,
        response.plan.document_instance_id,
        response.plan_hash,
        response.action_id,
      );
      setAppliedRevision(revision);
      if (revision == null) setError("План не применён. Проверьте состояние документа и пересчитайте предложение.");
    } catch (cause) {
      setError(parseIpcError(cause).message);
    } finally {
      setApplying(false);
    }
  };

  const operations = response?.plan.operations ?? [];
  const questions = response?.plan.questions ?? [];
  const preview = response?.preview;
  const applied = appliedRevision != null;
  const canApply = operations.length > 0 && questions.length === 0 && !preview?.error && !applied;
  const busy = planning || applying || settingsBusy || connectionBusy;

  return (
    <aside className="ai-panel" aria-label="AI-помощник">
      <header className="ai-header">
        <IconSparkles />
        <span className="ai-title">AI-помощник</span>
        <button className="icon-btn" aria-label="Закрыть AI-помощник" onClick={onClose}><IconClose /></button>
      </header>
      <div className="ai-body">
        <div className="ai-provider">
          <span className={`pill ${provider?.available ? "pill-positive" : "pill-warning"}`}>
            {provider == null ? "Проверка…" : provider.available ? "Доступен" : "Выключен"}
          </span>
          <span className="ai-provider-name">{providerTitle(provider)}</span>
          <button className="link-btn" onClick={() => setSettingsOpen((value) => !value)}>
            {settingsOpen ? "Скрыть настройки" : "Настроить"}
          </button>
        </div>

        {settingsOpen && (
          <section className="ai-settings" aria-label="Настройки AI-провайдера">
            <label>
              <span>Провайдер</span>
              <select
                value={settings.provider}
                disabled={busy}
                onChange={(event) => {
                  const next = event.target.value as SettingsDraft["provider"];
                  setSettings((current) => ({
                    provider: next,
                    base_url: next === "ollama" ? OLLAMA_DEFAULT_BASE : next === "openai" ? "" : current.base_url,
                    model: next === current.provider ? current.model : "",
                  }));
                  setSettingsError(null);
                  setSettingsMessage(null);
                }}
              >
                <option value="disabled">Выключен</option>
                <option value="ollama">Ollama на этом компьютере</option>
                <option value="openai">OpenAI-совместимый endpoint</option>
                {settings.provider === "scripted" && <option value="scripted" disabled>Scripted — режим разработки</option>}
              </select>
            </label>

            {(settings.provider === "ollama" || settings.provider === "openai") && (
              <>
                <label>
                  <span>Endpoint</span>
                  <input
                    type="url"
                    value={settings.base_url}
                    disabled={busy}
                    placeholder={settings.provider === "ollama" ? OLLAMA_DEFAULT_BASE : "https://provider.example/v1"}
                    spellCheck={false}
                    onChange={(event) => setSettings({ ...settings, base_url: event.target.value })}
                  />
                </label>
                <label>
                  <span>Model ID</span>
                  <input
                    value={settings.model}
                    disabled={busy}
                    placeholder={settings.provider === "ollama" ? "qwen3:4b" : "provider/model-name"}
                    spellCheck={false}
                    onChange={(event) => setSettings({ ...settings, model: event.target.value })}
                  />
                </label>
              </>
            )}

            {settings.provider === "openai" && (
              <label>
                <span>API key <small>необязательно для локального endpoint</small></span>
                <input
                  type="password"
                  value={newApiKey}
                  disabled={busy || clearApiKey}
                  placeholder={provider?.has_api_key ? "Ключ сохранён; введите новый для замены" : "Не сохранён"}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(event) => {
                    setNewApiKey(event.target.value);
                    setClearApiKey(false);
                  }}
                />
                {provider?.has_api_key && (
                  <button
                    type="button"
                    className="link-btn ai-key-action"
                    disabled={busy}
                    onClick={() => {
                      setNewApiKey("");
                      setClearApiKey((value) => !value);
                    }}
                  >
                    {clearApiKey ? "Не удалять ключ" : "Удалить сохранённый ключ"}
                  </button>
                )}
              </label>
            )}

            <p className="ai-data-note">{dataDisclosure(settings)}</p>
            {settings.provider === "openai" && (
              <p className="ai-secret-note">
                API key {provider?.secret_storage === "session"
                  ? "в browser dev-shim хранится только до остановки процесса"
                  : provider?.secret_storage === "environment"
                    ? "получен из PF_AI_KEY и не сохраняется приложением"
                    : "хранится в системном хранилище секретов и не записывается в проект или настройки"}.
              </p>
            )}
            {clearApiKey && <p className="ai-secret-note">Сохранённый API key будет удалён после сохранения.</p>}
            {settingsError && <p className="ai-settings-error" role="alert">{settingsError}</p>}
            {settingsMessage && (
              <p className={connectionWarning ? "ai-settings-warning" : "ai-settings-success"} role="status">
                {settingsMessage}
              </p>
            )}
            <div className="ai-settings-actions">
              <button
                className="btn btn-primary"
                disabled={busy || settings.provider === "scripted"}
                onClick={() => void saveSettings(false)}
              >
                {settingsBusy && !connectionBusy ? "Сохранение…" : "Сохранить"}
              </button>
              {settings.provider !== "disabled" && settings.provider !== "scripted" && (
                <button className="btn" disabled={busy} onClick={() => void saveSettings(true)}>
                  {connectionBusy ? "Проверка…" : "Сохранить и проверить"}
                </button>
              )}
            </div>
            {settings.provider !== "disabled" && settings.provider !== "scripted" && (
              <span className="ai-test-note">Проверка запрашивает только список `/models`; данные проекта не передаются.</span>
            )}
          </section>
        )}

        <label className="ai-prompt-label" htmlFor="ai-prompt">Опишите деталь или изменение</label>
        <textarea
          id="ai-prompt"
          className="ai-prompt"
          value={prompt}
          rows={5}
          disabled={busy}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              void requestPlan();
            }
          }}
        />
        <div className="ai-actions">
          {planning ? (
            <button className="btn" onClick={() => abortRef.current?.abort()}>Отменить запрос</button>
          ) : (
            <button
              className="btn btn-primary"
              data-cmd="ai.plan"
              disabled={!provider?.available || !prompt.trim() || busy}
              onClick={() => void requestPlan()}
            >
              {response ? "Пересчитать" : "Предложить план"}
            </button>
          )}
          <span className="ai-shortcut">⌘↵</span>
        </div>

        {error && <div className="error-box"><span className="error-title">AI-план не готов</span><p>{error}</p></div>}

        {response && (
          <section className="ai-plan" aria-live="polite">
            <div>
              <h2 className="panel-section">Предложение</h2>
              <p className="ai-summary">{response.plan.summary}</p>
            </div>

            {response.plan.assumptions.length > 0 && (
              <div className="ai-note ai-assumptions">
                <strong>Допущения</strong>
                <ul>{response.plan.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            )}

            {questions.length > 0 && (
              <div className="ai-note ai-questions">
                <strong>Нужно уточнить</strong>
                <ul>{questions.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            )}

            {operations.length > 0 && (
              <ol className="ai-operation-list">
                {operations.map((operation, index) => (
                  <li key={`${operation.command_id}-${index}`}>
                    <span className="ai-operation-title">{operationTitle(operation)}</span>
                    <span className="ai-operation-detail">{operationDetail(operation)}</span>
                  </li>
                ))}
              </ol>
            )}

            {preview && (
              <div className={`ai-preview ${preview.error ? "ai-preview-error" : ""}`}>
                <strong>Предпросмотр</strong>
                {preview.error ? (
                  <p>{preview.error.message}</p>
                ) : (
                  <p>
                    Объём {formatNumber(preview.stats?.volume)} мм³
                    {preview.stats?.solid_count != null ? ` · тел: ${preview.stats.solid_count}` : ""}
                  </p>
                )}
                <span>Рабочий документ ещё не изменён.</span>
              </div>
            )}

            <div className="ai-apply-row">
              <button className="btn btn-primary" disabled={!canApply || applying} onClick={() => void applyPlan()}>
                {applying ? "Применение…" : applied ? "Применено" : "Применить"}
              </button>
              {applied && <span className="pill pill-positive">Можно отменить одним ⌘Z</span>}
            </div>
          </section>
        )}

        <button className="link-btn ai-help-link" onClick={onOpenHelp}>Как AI-помощник работает с данными и моделью?</button>
      </div>
    </aside>
  );
}
