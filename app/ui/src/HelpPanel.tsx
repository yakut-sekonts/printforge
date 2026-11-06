import React, { useEffect, useMemo, useRef, useState } from "react";
import type { HelpArticle, HelpIndex, Lesson, CommandDef } from "./types";
import { Markdown, highlight } from "./markdown";
import { IconBack, IconClose, IconSearch } from "./icons";
import type { CommandRevealResult } from "./revealCommand";

export type TooltipMode = "teaching" | "brief" | "off";

interface Props {
  onClose: () => void;
  commands: CommandDef[];
  lessons: Lesson[];
  onStartLesson: (lessonId: string) => void;
  lessonDone: (lessonId: string) => boolean;
  tooltipMode: TooltipMode;
  onTooltipMode: (m: TooltipMode) => void;
  openArticleRequest: { helpId: string; seq: number } | null;
  highlightCommand: (commandId: string) => CommandRevealResult | Promise<CommandRevealResult> | void;
}

type View = { kind: "toc" } | { kind: "article"; article: HelpArticle };

export function HelpPanel(props: Props) {
  const [index, setIndex] = useState<HelpIndex | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<View>({ kind: "toc" });
  const [history, setHistory] = useState<View[]>([]);
  const [width, setWidth] = useState(380);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [commandMessage, setCommandMessage] = useState("");
  const handledArticle = useRef<number | null>(null);
  const resizeCleanup = useRef<(() => void) | null>(null);

  useEffect(() => {
    let alive = true;
    setLoadFailed(false);
    setIndex(null);
    fetch("/help/index.json")
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then((d: HelpIndex) => { if (alive) setIndex({ articles: Array.isArray(d?.articles) ? d.articles : [] }); })
      .catch(() => { if (alive) { setLoadFailed(true); setIndex({ articles: [] }); } });
    return () => { alive = false; };
  }, [loadAttempt]);

  useEffect(() => () => resizeCleanup.current?.(), []);

  const openArticle = (a: HelpArticle) => {
    setHistory((h) => [...h, view]);
    setView({ kind: "article", article: a });
    setCommandMessage("");
  };

  const openById = (helpId: string) => {
    const a = index?.articles.find((x) => x.help_id === helpId);
    if (a) openArticle(a);
  };

  useEffect(() => {
    if (props.openArticleRequest && handledArticle.current !== props.openArticleRequest.seq
      && index?.articles.some((article) => article.help_id === props.openArticleRequest?.helpId)) {
      handledArticle.current = props.openArticleRequest.seq;
      openById(props.openArticleRequest.helpId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.openArticleRequest?.seq, index]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !index) return [];
    return index.articles.filter((a) =>
      a.title.toLowerCase().includes(q) ||
      a.synonyms.some((s) => s.toLowerCase().includes(q)) ||
      a.body_markdown.toLowerCase().includes(q)
    );
  }, [query, index]);

  const goBack = () => {
    setHistory((h) => {
      if (!h.length) return h;
      const prev = h[h.length - 1];
      setView(prev);
      return h.slice(0, -1);
    });
  };

  const startResize = (e: React.PointerEvent) => {
    e.preventDefault();
    resizeCleanup.current?.();
    const startX = e.clientX;
    const startW = width;
    const move = (ev: PointerEvent) => {
      const w = Math.min(560, window.innerWidth - 16, Math.max(240, startW + (startX - ev.clientX)));
      setWidth(w);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      window.removeEventListener("blur", up);
      resizeCleanup.current = null;
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    window.addEventListener("blur", up);
    resizeCleanup.current = up;
  };

  const showCommand = async (commandId: string) => {
    try {
      const result = await props.highlightCommand(commandId);
      setCommandMessage(result?.message ?? "Проверьте выделенную команду в интерфейсе. Действие не выполнялось.");
    } catch {
      setCommandMessage("Не удалось показать команду. Условия выбора и расположение описаны в этой статье.");
    }
  };

  const articleCommands = (a: HelpArticle) =>
    a.commands.map((id) => props.commands.find((c) => c.command_id === id)).filter(Boolean) as CommandDef[];

  return (
    <aside className="help-panel" style={{ width, maxWidth: "calc(100% - 16px)" }} aria-label="Справочник">
      <div className="help-resize" onPointerDown={startResize} aria-hidden />
      <header className="help-header">
        {history.length > 0 && (
          <button className="icon-btn" data-cmd="help.back" aria-label="Назад по справке" onClick={goBack}>
            <IconBack />
          </button>
        )}
        <span className="help-title">Справочник</span>
        <button className="icon-btn" aria-label="Закрыть справочник" onClick={props.onClose}>
          <IconClose />
        </button>
      </header>

      {view.kind === "toc" && (
        <div className="help-body">
          <div className="help-search">
            <IconSearch />
            <input
              type="search"
              placeholder="Поиск по справке"
              aria-label="Поиск по справке"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {query.trim() ? (
            <section>
              {results.length === 0 && <p className="help-empty">Ничего не найдено{loadFailed ? " (индекс справки недоступен)" : ""}.</p>}
              {results.map((a) => {
                const q = query.trim().toLowerCase();
                const bodyIdx = a.body_markdown.toLowerCase().indexOf(q);
                const snippet = bodyIdx >= 0
                  ? a.body_markdown.slice(Math.max(0, bodyIdx - 40), bodyIdx + 80).replace(/[#*`]/g, "")
                  : "";
                return (
                  <button key={a.help_id} className="help-result" onClick={() => openArticle(a)}>
                    <span className="help-result-title">{highlight(a.title, query.trim())}</span>
                    {snippet && <span className="help-result-snippet">{highlight(snippet, query.trim())}</span>}
                  </button>
                );
              })}
            </section>
          ) : (
            <>
              <section>
                <h3 className="help-section">Оглавление</h3>
                {index === null && <p className="help-empty">Загрузка…</p>}
                {index?.articles.length === 0 && (
                  <p className="help-empty" role={loadFailed ? "alert" : undefined}>
                    {loadFailed ? "Индекс справки недоступен. Локальные материалы не загрузились." : "Статьи ещё не добавлены — справочник заполняется."}
                  </p>
                )}
                {loadFailed && <button className="btn" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>Повторить загрузку справки</button>}
                <ul className="help-toc">
                  {index?.articles.map((a) => (
                    <li key={a.help_id}>
                      <button className="link-btn" onClick={() => openArticle(a)}>{a.title}</button>
                    </li>
                  ))}
                </ul>
              </section>

              <section>
                <h3 className="help-section">Уроки</h3>
                <ul className="help-lessons">
                  {props.lessons.map((l, i) => (
                    <li key={l.lesson_id}>
                      <button className="help-lesson" data-cmd={`lesson.start.${l.lesson_id}`} aria-label={`Начать урок «${l.title}»`} onClick={() => props.onStartLesson(l.lesson_id)}>
                        <span className="help-lesson-title">
                          Урок {i + 1}. {l.title}
                          {props.lessonDone(l.lesson_id) && <span className="pill pill-positive">пройден</span>}
                        </span>
                        <span className="help-lesson-meta">{l.goal} · ~{l.duration_min} мин</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>

              <section>
                <h3 className="help-section">Настройки подсказок</h3>
                <div className="help-tooltip-modes" role="radiogroup" aria-label="Режим подсказок">
                  {([["teaching", "Обучающий"], ["brief", "Краткий"], ["off", "Без подсказок"]] as [TooltipMode, string][]).map(([m, label]) => (
                    <label key={m} className={`radio-row ${props.tooltipMode === m ? "active" : ""}`}>
                      <input type="radio" name="tooltip-mode" checked={props.tooltipMode === m} onChange={() => props.onTooltipMode(m)} />
                      {label}
                    </label>
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      )}

      {view.kind === "article" && (
        <div className="help-body help-article">
          <h2>{view.article.title}</h2>
          <Markdown source={view.article.body_markdown} />
          {articleCommands(view.article).length > 0 && (
            <div className="help-show-ui">
              {articleCommands(view.article).map((c) => (
                <button key={c.command_id} className="btn" onClick={() => void showCommand(c.command_id)}>
                  Показать в интерфейсе: {c.title}
                </button>
              ))}
            </div>
          )}
          {commandMessage && <p className="help-command-message" role="status">{commandMessage}</p>}
          {view.article.related.length > 0 && (
            <div className="help-related">
              <h3 className="help-section">См. также</h3>
              <ul className="help-toc">
                {view.article.related.map((id) => {
                  const a = index?.articles.find((x) => x.help_id === id);
                  return a ? (
                    <li key={id}><button className="link-btn" onClick={() => openArticle(a)}>{a.title}</button></li>
                  ) : null;
                })}
              </ul>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
