import React, { useCallback, useEffect, useRef, useState } from "react";
import type {
  CommandDef, DocState, Lesson, MeshData, LessonCheck, GeoError,
  TemplateDef, EdgeRef, PrintCheck, ImportResult, DocStats,
} from "./types";
import { backend, expandTilde, parseIpcError } from "./backend";
import { evalExpression } from "./expr";
import { Viewport, faceArea, ViewName } from "./viewport";
import { TopBar, LeftPanel, StatusBar, EmptyState, cmdEnabled } from "./components";
import { ParamsPanel, FilletUi } from "./ParamsPanel";
import { HelpPanel, TooltipMode } from "./HelpPanel";
import { Tooltips } from "./Tooltips";
import { LessonBar, LessonRun, StepStatus } from "./LessonBar";

const TOOLTIP_KEY = "pf-tooltip-mode";
const lessonKey = (id: string) => `pf-lesson-${id}`;

function loadLessonProgress(id: string, len: number): StepStatus[] {
  try {
    const raw = localStorage.getItem(lessonKey(id));
    if (raw) {
      const arr = JSON.parse(raw) as StepStatus[];
      if (Array.isArray(arr) && arr.length === len) return arr;
    }
  } catch { /* игнор */ }
  return Array(len).fill("pending");
}

export default function App() {
  const [commands, setCommands] = useState<CommandDef[]>([]);
  const [templates, setTemplates] = useState<TemplateDef[]>([]);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [doc, setDoc] = useState<DocState | null>(null);
  const [mesh, setMesh] = useState<MeshData | null>(null);
  const [computing, setComputing] = useState(false);
  const [selectedFace, setSelectedFace] = useState<number | null>(null);
  const [selectedPartId, setSelectedPartId] = useState<string | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [whatIsThis, setWhatIsThis] = useState(false);
  const [articleReq, setArticleReq] = useState<{ helpId: string; seq: number } | null>(null);
  const [tooltipMode, setTooltipMode] = useState<TooltipMode>(
    () => (localStorage.getItem(TOOLTIP_KEY) as TooltipMode) || "teaching"
  );
  const [lessonRun, setLessonRun] = useState<LessonRun | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [savePath, setSavePath] = useState("~/plate.printforge");
  const [openPath, setOpenPath] = useState("~/plate.printforge");
  const [exportPath, setExportPath] = useState("~/plate.stl");
  const [fillet, setFillet] = useState<FilletUi>({ active: false, selected: null, radius: "2" });
  const [printChecks, setPrintChecks] = useState<PrintCheck[] | null>(null);
  const [printBusy, setPrintBusy] = useState(false);
  const [importPreview, setImportPreview] = useState<ImportResult | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importedStats, setImportedStats] = useState<DocStats | null>(null);

  const viewportRef = useRef<Viewport | null>(null);
  const viewportEl = useRef<HTMLDivElement>(null);
  const meshToken = useRef(0);
  const docRef = useRef<DocState | null>(null);
  const lessonRef = useRef<LessonRun | null>(null);
  const filletRef = useRef(fillet);
  docRef.current = doc;
  lessonRef.current = lessonRun;
  filletRef.current = fillet;

  // ---------- загрузка реестров ----------
  useEffect(() => {
    fetch("/commands.json").then((r) => r.json()).then((d) => setCommands(d.commands ?? [])).catch(() => {});
    fetch("/templates.json").then((r) => r.json()).then((d) => setTemplates(d.templates ?? [])).catch(() => {});
    fetch("/lessons.json").then((r) => r.json()).then((d) => setLessons(d.lessons ?? [])).catch(() => {});
    backend.docGetState()
      .then((s) => { if (s && s.stats) applyDoc(s); })
      .catch(() => { /* бэкенд недоступен — пустое состояние */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- viewport ----------
  useEffect(() => {
    if (!viewportEl.current) return;
    const vp = new Viewport(viewportEl.current, {
      onHoverFace: () => {},
      onSelectFace: (face) => {
        setSelectedFace(face);
        vp.setSelectedFace(face);
        if (face != null) lessonEvent({ type: "face_selected" });
      },
      onCameraRotated: () => lessonEvent({ type: "camera_rotated" }),
      onCameraZoomed: () => lessonEvent({ type: "camera_zoomed" }),
    });
    viewportRef.current = vp;
    return () => { vp.dispose(); viewportRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    viewportRef.current?.setMesh(mesh);
  }, [mesh]);

  useEffect(() => {
    document.body.classList.toggle("what-is-this", whatIsThis);
  }, [whatIsThis]);

  // ---------- работа с документом ----------
  const applyDoc = useCallback((state: DocState) => {
    const cur = docRef.current;
    // страж устаревших ответов: та же пара doc_id+slot, но меньшая ревизия
    if (cur && cur.slot === state.slot && cur.doc_id === state.doc_id && state.revision < cur.revision) return;
    setDoc(state);
    if (state.stats?.is_valid) {
      const token = ++meshToken.current;
      setComputing(true);
      backend.docGetMesh()
        .then((m) => {
          if (token === meshToken.current) {
            setMesh(m);
            setImportedStats(null); // снова показываем параметрическую модель
          }
        })
        .catch(() => {})
        .finally(() => { if (token === meshToken.current) setComputing(false); });
    } else {
      setMesh(null);
    }
  }, []);

  const runBackend = useCallback(async (fn: () => Promise<DocState>): Promise<DocState | null> => {
    setComputing(true);
    try {
      const state = await fn();
      applyDoc(state);
      return state;
    } catch (e) {
      const err = e as GeoError;
      setStatusMsg(`Ошибка: ${err.message ?? String(e)}`);
      return null;
    } finally {
      setComputing(false);
    }
  }, [applyDoc]);

  // ---------- уроки ----------
  const persistProgress = (run: LessonRun) => {
    localStorage.setItem(lessonKey(run.lesson.lesson_id), JSON.stringify(run.statuses));
  };

  const advanceIfDone = useCallback((run: LessonRun): LessonRun => {
    const statuses = [...run.statuses];
    let idx = run.stepIndex;
    while (idx < run.lesson.steps.length && (statuses[idx] === "done" || statuses[idx] === "skipped")) idx++;
    const next = { ...run, statuses, stepIndex: idx };
    persistProgress(next);
    return next;
  }, []);

  const checkParams = useCallback((check: LessonCheck, state: DocState): boolean => {
    if (check.template && state.template !== check.template) return false;
    if (!check.params) return true;
    for (const [k, v] of Object.entries(check.params)) {
      const actual = state.params?.[k];
      if (actual == null || Math.abs(actual - v) > 1e-6) return false;
    }
    if (check.hole_centers_abs_x != null) {
      const centers = state.stats?.hole_centers ?? [];
      const ok = centers.some(([x]) => Math.abs(Math.abs(x) - check.hole_centers_abs_x!) < 1e-6);
      if (!ok) return false;
    }
    return true;
  }, []);

  const lessonEvent = useCallback((ev: {
    type: string; command_id?: string; state?: DocState;
    op?: string; radius?: number; code?: string; mode?: string;
    checks?: { id: string; status: string }[];
  }) => {
    const run = lessonRef.current;
    if (!run || run.paused || run.stepIndex >= run.lesson.steps.length) return;
    const step = run.lesson.steps[run.stepIndex];
    const check = step.check;
    let ok = false;
    switch (check.type) {
      case "camera_rotated": ok = ev.type === "camera_rotated"; break;
      case "camera_zoomed": ok = ev.type === "camera_zoomed"; break;
      case "command": ok = ev.type === "command" && ev.command_id === check.command_id; break;
      case "face_selected": ok = ev.type === "face_selected"; break;
      case "params": ok = ev.state != null && checkParams(check, ev.state); break;
      case "saved": ok = ev.type === "saved"; break;
      case "reopened": ok = ev.type === "reopened" && (!check.params || (ev.state != null && checkParams(check, ev.state))); break;
      case "exported": ok = ev.type === "exported"; break;
      case "operation":
        ok = ev.type === "operation" && ev.op === check.op
          && (check.radius == null || Math.abs((ev.radius ?? -1) - check.radius) < 1e-9);
        break;
      case "error_shown": ok = ev.type === "error_shown" && (!check.code || ev.code === check.code); break;
      case "imported": ok = ev.type === "imported" && (!check.mode || ev.mode === check.mode); break;
      case "check_result":
        ok = ev.type === "check_result"
          && (ev.checks ?? []).some((c) => c.id === check.id && c.status === check.status);
        break;
    }
    if (ok) {
      const statuses = [...run.statuses];
      statuses[run.stepIndex] = "done";
      setLessonRun(advanceIfDone({ ...run, statuses }));
    }
  }, [advanceIfDone, checkParams]);

  useEffect(() => {
    const run = lessonRun;
    if (!run || run.stepIndex >= run.lesson.steps.length) return;
    const check = run.lesson.steps[run.stepIndex].check;
    if (check.type === "params" && doc) lessonEvent({ type: "params", state: doc });
    if (check.type === "error_shown" && doc?.error) lessonEvent({ type: "error_shown", code: doc.error.code });
  }, [doc, lessonRun, lessonEvent]);

  const startLesson = useCallback(async (lessonId: string) => {
    const lesson = lessons.find((l) => l.lesson_id === lessonId);
    if (!lesson) return;
    setComputing(true);
    try {
      let state = await backend.docNewTutorial();
      applyDoc(state);
      const idx = lessons.indexOf(lesson);
      if (idx === 0 || idx === 2) {
        state = await backend.docCreatePlate({ length: 80, width: 40, height: 6, hole_diameter: 4, hole_offset: 10 });
        applyDoc(state);
      }
      const statuses = loadLessonProgress(lesson.lesson_id, lesson.steps.length).map(() => "pending" as StepStatus);
      const run: LessonRun = {
        lesson, lessonIndex: idx, totalLessons: lessons.length,
        stepIndex: 0, statuses, paused: false,
      };
      persistProgress(run);
      setLessonRun(run);
      setSelectedFace(null);
    } catch (e) {
      setStatusMsg(`Не удалось начать урок: ${(e as GeoError).message ?? e}`);
    } finally {
      setComputing(false);
    }
  }, [lessons, applyDoc]);

  const exitLesson = useCallback(async () => {
    setLessonRun(null);
    setSelectedFace(null);
    try {
      const state = await backend.docSwitchSlot("main");
      applyDoc(state);
    } catch { /* бэкенд недоступен */ }
  }, [applyDoc]);

  const lessonDone = useCallback((lessonId: string) => {
    const lesson = lessons.find((l) => l.lesson_id === lessonId);
    if (!lesson) return false;
    const statuses = loadLessonProgress(lessonId, lesson.steps.length);
    return statuses.every((s) => s !== "pending");
  }, [lessons]);

  // ---------- команды документа ----------
  const createFromTemplate = useCallback(async (t: TemplateDef, params?: Record<string, number>) => {
    const state = await runBackend(() => backend.docCreate(t.template_id, params));
    if (state) lessonEvent({ type: "params", state });
  }, [runBackend, lessonEvent]);

  // совместимость с уроком «Первая деталь»: создание учебной пластины
  const createPlate = useCallback(async () => {
    const state = await runBackend(() => backend.docCreatePlate({ length: 80, width: 40, height: 6, hole_diameter: 4, hole_offset: 10 }));
    if (state) lessonEvent({ type: "params", state });
  }, [runBackend, lessonEvent]);

  const applyField = useCallback(async (name: string, raw: string, partId?: string) => {
    const cur = docRef.current;
    if (!cur) return;
    const part = partId ? cur.parts?.find((p) => p.part_id === partId) : cur.parts?.[0];
    let num: number;
    try { num = evalExpression(raw, { ...(part?.params ?? cur.params) }); }
    catch (e) { setStatusMsg(`Ошибка выражения: ${(e as Error).message}`); return; }
    const state = await runBackend(() => backend.docSetParameter(name, num, raw, partId));
    if (state) lessonEvent({ type: "params", state });
  }, [runBackend, lessonEvent]);

  // сброс выбора детали, если она исчезла из живых тел
  useEffect(() => {
    if (!selectedPartId) return;
    const live = doc?.stats?.parts;
    if (live && !live.some((p) => p.part_id === selectedPartId)) setSelectedPartId(null);
  }, [doc, selectedPartId]);

  const activePartId = useCallback((): string | undefined => {
    const cur = docRef.current;
    const live = cur?.stats?.parts;
    if (selectedPartId && live?.some((p) => p.part_id === selectedPartId)) return selectedPartId;
    return live?.[0]?.part_id ?? cur?.parts?.[0]?.part_id;
  }, [selectedPartId]);

  const addPart = useCallback(async (t: TemplateDef) => {
    await runBackend(() => backend.docAddPart(t.template_id));
  }, [runBackend]);

  const runBoolean = useCallback(async (kind: "union" | "subtract" | "intersect", keepTool: boolean) => {
    const live = docRef.current?.stats?.parts ?? [];
    if (live.length < 2) return;
    const target = live.find((p) => p.part_id === selectedPartId) ?? live[0];
    const tool = live[(live.indexOf(target) + 1) % live.length];
    await runBackend(() => backend.docBoolean(kind, target.part_id, tool.part_id, keepTool));
  }, [runBackend, selectedPartId]);

  const runArray = useCallback(async (count: number, step: [number, number, number]) => {
    const id = activePartId();
    if (!id) return;
    await runBackend(() => backend.docArray(id, count, step));
  }, [runBackend, activePartId]);

  const runMirror = useCallback(async (plane: "XY" | "XZ" | "YZ") => {
    const id = activePartId();
    if (!id) return;
    await runBackend(() => backend.docMirror(id, plane));
  }, [runBackend, activePartId]);

  const runSplit = useCallback(async (plane: "XY" | "XZ" | "YZ", offset: number) => {
    const id = activePartId();
    if (!id) return;
    await runBackend(() => backend.docSplit(id, plane, offset));
  }, [runBackend, activePartId]);

  const runTransform = useCallback(async (translate: [number, number, number]) => {
    const id = activePartId();
    if (!id) return;
    await runBackend(() => backend.docTransform(id, translate));
  }, [runBackend, activePartId]);

  // ---------- скругление ----------
  const startFillet = useCallback(() => {
    setFillet({ active: true, selected: null, radius: filletRef.current.radius });
  }, []);

  const cancelFillet = useCallback(() => {
    setFillet((f) => ({ ...f, active: false, selected: null }));
    viewportRef.current?.setEdgeMarker(null);
  }, []);

  const selectEdge = useCallback((e: EdgeRef) => {
    setFillet((f) => ({ ...f, selected: e }));
    viewportRef.current?.setEdgeMarker(e);
  }, []);

  const applyFillet = useCallback(async () => {
    const f = filletRef.current;
    if (!f.selected) return;
    const radius = Number(f.radius.replace(",", "."));
    if (!Number.isFinite(radius) || radius <= 0) {
      setStatusMsg("Радиус должен быть положительным числом");
      return;
    }
    const state = await runBackend(() => backend.docFillet(f.selected!, radius, activePartId()));
    if (state && !state.error) {
      cancelFillet();
      lessonEvent({ type: "operation", op: "fillet", radius });
    }
  }, [runBackend, cancelFillet, lessonEvent, activePartId]);

  const clearErrorOrUndo = useCallback(() => {
    const code = docRef.current?.error?.code;
    if (code === "fillet_failed" || code === "reselect_required") {
      void runBackend(() => backend.docClearError());
    } else {
      void runBackend(() => backend.docUndo());
    }
  }, [runBackend]);

  // ---------- проверка печати ----------
  const runPrintCheck = useCallback(async (printer: { x: number; y: number; z: number }) => {
    setPrintBusy(true);
    try {
      const res = await backend.printCheck(printer);
      setPrintChecks(res.checks ?? []);
      lessonEvent({ type: "check_result", checks: res.checks ?? [] });
    } catch (e) {
      setStatusMsg(`Ошибка проверки: ${parseIpcError(e).message}`);
    } finally {
      setPrintBusy(false);
    }
  }, []);

  // ---------- импорт ----------
  const runImport = useCallback(async (path: string, format: "step" | "stl", unitScale?: number) => {
    setImportBusy(true);
    try {
      const res = await backend.docImport(expandTilde(path), format, unitScale);
      if (format === "stl" && unitScale === undefined) {
        // первый проход: показываем габарит и спрашиваем единицы
        setImportPreview(res);
      } else {
        setMesh(res.mesh);
        setImportedStats(res.stats);
        setImportPreview(null);
        setSelectedFace(null);
        const tris = res.mesh.triangle_count;
        setStatusMsg(`Импортировано: ${expandTilde(path)} — ${tris} треугольников`);
        lessonEvent({ type: "imported", mode: res.mode });
      }
    } catch (e) {
      setStatusMsg(`Ошибка импорта: ${parseIpcError(e).message}`);
      setImportPreview(null);
    } finally {
      setImportBusy(false);
    }
  }, []);

  // ---------- файлы ----------
  const doSave = useCallback(async () => {
    const state = await runBackend(() => backend.docSave(expandTilde(savePath)));
    if (state) {
      setStatusMsg(`Сохранено: ${state.path ?? expandTilde(savePath)}`);
      lessonEvent({ type: "saved" });
    }
  }, [savePath, runBackend, lessonEvent]);

  const doOpen = useCallback(async () => {
    const state = await runBackend(() => backend.docOpen(expandTilde(openPath)));
    if (state) {
      setStatusMsg(`Открыто: ${state.path ?? expandTilde(openPath)}`);
      lessonEvent({ type: "reopened", state });
    }
  }, [openPath, runBackend, lessonEvent]);

  const doExport = useCallback(async (format: "stl" | "step" | "3mf") => {
    const path = expandTilde(exportPath).replace(/\.(stl|step|stp|3mf)$/i, "") + "." + format;
    setComputing(true);
    try {
      const res = await backend.docExport(path, format);
      const kb = (res.bytes / 1024).toFixed(1);
      const vol = Math.round(res.stats.volume * 10) / 10;
      setStatusMsg(`Экспортировано: ${res.path} — ${kb} КБ, объём ${vol} мм³`);
      lessonEvent({ type: "exported" });
    } catch (e) {
      setStatusMsg(`Ошибка экспорта: ${parseIpcError(e).message}`);
    } finally {
      setComputing(false);
    }
  }, [exportPath, lessonEvent]);

  const viewCommand = useCallback((id: string) => {
    const vp = viewportRef.current;
    if (!vp) return;
    if (id === "view.fit") vp.fit();
    else if (id === "view.proj") vp.toggleProjection();
    else vp.setView(id.replace("view.", "") as ViewName);
    lessonEvent({ type: "command", command_id: id });
  }, [lessonEvent]);

  const openHelpArticle = useCallback((helpId: string) => {
    setHelpOpen(true);
    setArticleReq((r) => ({ helpId, seq: (r?.seq ?? 0) + 1 }));
  }, []);

  const highlightCommand = useCallback((commandId: string) => {
    const el = document.querySelector<HTMLElement>(`[data-cmd="${commandId}"]`);
    if (!el) return;
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    el.classList.add("cmd-highlight");
    window.setTimeout(() => el.classList.remove("cmd-highlight"), 1200);
  }, []);

  const runCommand = useCallback((id: string) => {
    const cmd = commands.find((c) => c.command_id === id);
    if (cmd && !cmdEnabled(cmd, docRef.current)) return;
    const template = templates.find((t) => t.command_id === id);
    if (template) { void createFromTemplate(template); return; }
    switch (id) {
      case "op.undo": void runBackend(() => backend.docUndo()); break;
      case "op.redo": void runBackend(() => backend.docRedo()); break;
      case "doc.save": void doSave(); break;
      case "doc.open": void doOpen(); break;
      case "export.stl": void doExport("stl"); break;
      case "export.step": void doExport("step"); break;
      case "export.3mf": void doExport("3mf"); break;
      case "op.fillet": startFillet(); break;
      case "app.help.open": setHelpOpen((v) => !v); break;
      case "app.help.what_is_this": setWhatIsThis((v) => !v); break;
    }
  }, [commands, templates, createFromTemplate, runBackend, doSave, doOpen, doExport, startFillet]);

  // ---------- режим «Что это?» ----------
  useEffect(() => {
    if (!whatIsThis) return;
    const handler = (e: MouseEvent) => {
      const el = (e.target as HTMLElement).closest?.("[data-cmd]") as HTMLElement | null;
      if (!el) return;
      e.preventDefault();
      e.stopPropagation();
      const cmd = commands.find((c) => c.command_id === el.dataset.cmd);
      setWhatIsThis(false);
      if (cmd) openHelpArticle(cmd.help_id);
      else {
        const t = templates.find((x) => x.command_id === el.dataset.cmd);
        if (t) openHelpArticle(t.help_id);
        else setHelpOpen(true);
      }
    };
    document.addEventListener("click", handler, true);
    return () => document.removeEventListener("click", handler, true);
  }, [whatIsThis, commands, templates, openHelpArticle]);

  // ---------- клавиатура ----------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) {
          if (docRef.current?.can_redo) void runBackend(() => backend.docRedo());
        } else if (docRef.current?.can_undo) {
          void runBackend(() => backend.docUndo());
        }
      } else if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (docRef.current) void doSave();
      } else if (mod && e.key.toLowerCase() === "o") {
        e.preventDefault();
        void doOpen();
      } else if (mod && e.key === "/") {
        e.preventDefault();
        setHelpOpen((v) => !v);
      } else if (e.key === "Escape" && e.shiftKey) {
        e.preventDefault();
        setWhatIsThis((v) => !v);
      } else if (e.key === "Escape") {
        if (filletRef.current.active) cancelFillet();
        else if (whatIsThis) setWhatIsThis(false);
        else if (helpOpen) setHelpOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [whatIsThis, helpOpen, runBackend, doSave, doOpen, cancelFillet]);

  const faceAreaValue = mesh && selectedFace != null ? faceArea(mesh, selectedFace) : null;
  const docName = doc?.path ? doc.path.split("/").pop()! : "Без названия";
  const hasBody = (!!doc?.stats?.is_valid || !!importedStats) && !!mesh;

  return (
    <div className="app-shell">
      <TopBar commands={commands} doc={doc} docName={docName} onCommand={runCommand} />
      <div className="app-main">
        <LeftPanel
          doc={doc}
          templates={templates}
          importedStats={importedStats}
          selectedPartId={selectedPartId}
          onSelectPart={setSelectedPartId}
          onCreateTemplate={(t) => void createFromTemplate(t)}
        />
        <main className="scene-area">
          <div className="viewport" ref={viewportEl} aria-label="Сцена 3D" />
          <div className="view-toolbar" role="toolbar" aria-label="Виды">
            <button className="btn" data-cmd="view.top" aria-label="Вид сверху" onClick={() => viewCommand("view.top")}>Сверху</button>
            <button className="btn" data-cmd="view.front" aria-label="Вид спереди" onClick={() => viewCommand("view.front")}>Спереди</button>
            <button className="btn" data-cmd="view.side" aria-label="Вид сбоку" onClick={() => viewCommand("view.side")}>Сбоку</button>
            <button className="btn" data-cmd="view.iso" aria-label="Изометрия" onClick={() => viewCommand("view.iso")}>Изометрия</button>
            <button className="btn" data-cmd="view.fit" aria-label="Показать всё" onClick={() => viewCommand("view.fit")}>Показать всё</button>
            <button className="btn" data-cmd="view.proj" aria-label="Переключить перспективную и ортографическую проекцию" onClick={() => viewCommand("view.proj")}>
              Перспектива/Орто
            </button>
          </div>
          {!hasBody && !computing && (
            <EmptyState
              templates={templates}
              onCreateTemplate={(t) => void createFromTemplate(t)}
              onLesson={() => void startLesson("first-part")}
            />
          )}
          {lessonRun && (
            <LessonBar
              run={lessonRun}
              onSkip={() => {
                const statuses = [...lessonRun.statuses];
                statuses[lessonRun.stepIndex] = "skipped";
                setLessonRun(advanceIfDone({ ...lessonRun, statuses }));
              }}
              onTogglePause={() => setLessonRun({ ...lessonRun, paused: !lessonRun.paused })}
              onExit={() => void exitLesson()}
              onRestart={() => void startLesson(lessonRun.lesson.lesson_id)}
            />
          )}
        </main>
        <ParamsPanel
          doc={doc}
          templates={templates}
          selectedFace={selectedFace}
          faceArea={faceAreaValue}
          onApplyField={(n, r, p) => void applyField(n, r, p)}
          selectedPartId={selectedPartId}
          onAddPart={(t) => void addPart(t)}
          onBoolean={(k, keep) => void runBoolean(k, keep)}
          onArray={(c, s) => void runArray(c, s)}
          onMirror={(pl) => void runMirror(pl)}
          onSplit={(pl, off) => void runSplit(pl, off)}
          onTransform={(tr) => void runTransform(tr)}
          fillet={fillet}
          onStartFillet={startFillet}
          onSelectEdge={selectEdge}
          onFilletRadius={(v) => setFillet((f) => ({ ...f, radius: v }))}
          onApplyFillet={() => void applyFillet()}
          onCancelFillet={cancelFillet}
          onClearError={clearErrorOrUndo}
          printChecks={printChecks}
          printBusy={printBusy}
          onPrintCheck={(p) => void runPrintCheck(p)}
          importPreview={importPreview}
          importBusy={importBusy}
          onImport={(p, f, s) => void runImport(p, f, s)}
          onCancelImportPreview={() => setImportPreview(null)}
          savePath={savePath} setSavePath={setSavePath}
          openPath={openPath} setOpenPath={setOpenPath}
          exportPath={exportPath} setExportPath={setExportPath}
          onSave={() => void doSave()}
          onOpen={() => void doOpen()}
          onExport={(f) => void doExport(f)}
        />
        {helpOpen && (
          <HelpPanel
            onClose={() => setHelpOpen(false)}
            commands={commands}
            lessons={lessons}
            onStartLesson={(id) => void startLesson(id)}
            lessonDone={lessonDone}
            tooltipMode={tooltipMode}
            onTooltipMode={(m) => { setTooltipMode(m); localStorage.setItem(TOOLTIP_KEY, m); }}
            openArticleRequest={articleReq}
            highlightCommand={highlightCommand}
          />
        )}
      </div>
      <StatusBar
        doc={doc}
        computing={computing}
        message={statusMsg}
        selectedFace={selectedFace}
        faceArea={faceAreaValue}
      />
      <Tooltips mode={tooltipMode} commands={commands} onOpenArticle={openHelpArticle} />
    </div>
  );
}
