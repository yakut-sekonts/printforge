import React, { useCallback, useEffect, useRef, useState } from "react";
import type {
  CommandDef, ConstrainedSketch, ConstrainedSketchExtrudeArgs, DocState, Lesson, MeshData,
  LessonCheck, GeoError, ClearanceCalibrationArgs,
  TemplateDef, EdgeRef, EdgeFeatureKind, FaceDomeArgs, FaceFeatureArgs, FitPocketArgs,
  ImageReliefPreview, ImageReliefSettings, PrintCheck, ImportResult,
  DocStats, AiOperation, DraftPrismArgs, LoftArgs, NativeE2eConfig, PerformanceConfig, RevolveArgs,
  RibArgs, SheetBendArgs, ShellArgs, SketchExtrudeArgs, SketchSolveResult,
  SplitConnectorPairArgs, SweepArgs,
  TextReliefArgs, ThreadPairArgs,
  VectorExtrudeArgs,
} from "./types";
import { backend, expandTilde, isTauri, parseIpcError } from "./backend";
import { evalExpression } from "./expr";
import { Viewport, faceArea, ViewName } from "./viewport";
import type { TransformAxis } from "./viewport";
import {
  pushPullDelta, pushPullValue, resolveFaceEditTarget, resolveFaceFeatureTarget,
  resolveSheetBendTarget, resolveGenericFaceEditTarget,
} from "./faceEditing";
import { partIdForSolid, parseMillimeters, selectedBoundsCenter, solidIndicesForParts, togglePartSelection } from "./sceneSelection";
import type {
  FaceDomePreview, FaceFeaturePreview, FaceFeatureTarget, SheetBendPreview,
} from "./faceEditing";
import { TopBar, LeftPanel, StatusBar, EmptyState, cmdEnabled } from "./components";
import { ParamsPanel } from "./ParamsPanel";
import type { EdgeToolUi, PushPullUi } from "./ParamsPanel";
import { HelpPanel, TooltipMode } from "./HelpPanel";
import { Tooltips } from "./Tooltips";
import { LessonBar, LessonRun, StepStatus } from "./LessonBar";
import { AiPanel } from "./AiPanel";
import { SelectionCoach } from "./SelectionCoach";
import { PrimitivePicker } from "./PrimitivePicker";

const TOOLTIP_KEY = "pf-tooltip-mode";
const lessonKey = (id: string, version = 1) => `pf-lesson-${id}-v${version}`;

function loadLessonProgress(id: string, len: number, version = 1): StepStatus[] {
  try {
    const raw = localStorage.getItem(lessonKey(id, version));
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
  const [meshLoading, setMeshLoading] = useState(false);
  const [geometryBusy, setGeometryBusy] = useState(false);
  const [geometryCancelling, setGeometryCancelling] = useState(false);
  const [selectedFace, setSelectedFace] = useState<number | null>(null);
  const [selectedPartId, setSelectedPartId] = useState<string | null>(null);
  const [selectedPartIds, setSelectedPartIds] = useState<string[]>([]);
  const [moveMode, setMoveMode] = useState(false);
  const [movePreview, setMovePreview] = useState<{ axis: TransformAxis; delta: number } | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
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
  const [edgeTool, setEdgeTool] = useState<EdgeToolUi>({
    active: false,
    kind: "fillet",
    selected: null,
    partId: null,
    size: "2",
  });
  const [pushPull, setPushPull] = useState<PushPullUi>({
    target: null,
    value: "",
    dragging: false,
    reason: null,
  });
  const [faceFeatureTarget, setFaceFeatureTarget] = useState<FaceFeatureTarget | null>(null);
  const [sheetBendTarget, setSheetBendTarget] = useState<FaceFeatureTarget | null>(null);
  const [faceFeatureReason, setFaceFeatureReason] = useState<string | null>(null);
  const [printChecks, setPrintChecks] = useState<PrintCheck[] | null>(null);
  const [printBusy, setPrintBusy] = useState(false);
  const [importPreview, setImportPreview] = useState<ImportResult | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importedStats, setImportedStats] = useState<DocStats | null>(null);
  const [constraintSolution, setConstraintSolution] = useState<SketchSolveResult | null>(null);
  const [imageReliefPreview, setImageReliefPreview] = useState<ImageReliefPreview | null>(null);
  const [measureResult, setMeasureResult] = useState<{
    source?: string; bbox?: number[]; volume?: number;
    faceDiameter?: number; faceError?: string; distance?: number;
  } | null>(null);
  const [measureBusy, setMeasureBusy] = useState(false);
  const [performanceConfig, setPerformanceConfig] = useState<PerformanceConfig | null>(null);
  const [nativeE2eConfig, setNativeE2eConfig] = useState<NativeE2eConfig | null>(null);

  const viewportRef = useRef<Viewport | null>(null);
  const viewportEl = useRef<HTMLDivElement>(null);
  const meshToken = useRef(0);
  const geometryOperationCount = useRef(0);
  const documentActionPending = useRef(false);
  const docRef = useRef<DocState | null>(null);
  const meshRef = useRef<MeshData | null>(null);
  const lessonRef = useRef<LessonRun | null>(null);
  const edgeToolRef = useRef(edgeTool);
  const selectedPartIdsRef = useRef(selectedPartIds);
  const edgeSelectHandlerRef = useRef<(edge: EdgeRef) => void>(() => {});
  const pushPullRef = useRef(pushPull);
  const pushPullHandlersRef = useRef({
    start: () => {},
    preview: (_delta: number) => {},
    commit: (_delta: number) => {},
  });
  const partMoveHandlersRef = useRef({
    preview: (_axis: TransformAxis, _delta: number) => {},
    commit: (_axis: TransformAxis, _delta: number) => {},
  });
  const performanceReported = useRef(false);
  const nativeE2eStarted = useRef(false);
  docRef.current = doc;
  meshRef.current = mesh;
  lessonRef.current = lessonRun;
  edgeToolRef.current = edgeTool;
  selectedPartIdsRef.current = selectedPartIds;
  pushPullRef.current = pushPull;

  // ---------- загрузка реестров ----------
  useEffect(() => {
    fetch("/commands.json").then((r) => r.json()).then((d) => setCommands(d.commands ?? [])).catch(() => {});
    fetch("/templates.json").then((r) => r.json()).then((d) => setTemplates(d.templates ?? [])).catch(() => {});
    fetch("/lessons.json").then((r) => r.json()).then((d) => setLessons(d.lessons ?? [])).catch(() => {});
    const loadInitialDocument = async () => {
      try {
        const [perfConfig, e2eConfig] = isTauri()
          ? await Promise.all([backend.performanceConfig(), backend.nativeE2eConfig()])
          : [null, null];
        setPerformanceConfig(perfConfig);
        setNativeE2eConfig(e2eConfig);
        const state = perfConfig?.enabled && perfConfig.mode === "workload" && perfConfig.project_path
          ? await backend.docOpen(perfConfig.project_path)
          : await backend.docGetState();
        if (state?.stats) applyDoc(state);
      } catch { /* бэкенд недоступен — пустое состояние */ }
    };
    void loadInitialDocument();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- viewport ----------
  useEffect(() => {
    if (!viewportEl.current) return;
    const vp = new Viewport(viewportEl.current, {
      onHoverFace: () => {},
      onSelectFace: (face, additive = false) => {
        setEdgeTool((current) => ({ ...current, active: false, selected: null, partId: null }));
        setSelectedFace(face);
        vp.setSelectedFace(face);
        if (face != null) {
          const solidIndex = meshRef.current?.face_ranges
            .find((candidate) => candidate.face_index === face)?.solid_index;
          const partId = solidIndex == null ? null : partIdForSolid(docRef.current?.stats?.parts ?? [], solidIndex);
          if (partId) {
            const next = togglePartSelection(selectedPartIdsRef.current, partId, additive);
            setSelectedPartId(next[next.length - 1] ?? null);
            setSelectedPartIds(next);
            if (additive) { setSelectedFace(null); vp.setSelectedFace(null); }
          }
          lessonEvent({ type: "face_selected" });
        } else if (!additive) {
          setSelectedPartId(null);
          setSelectedPartIds([]);
        }
      },
      onSelectEdge: (edge) => edgeSelectHandlerRef.current(edge),
      onPushPullStart: () => pushPullHandlersRef.current.start(),
      onPushPullPreview: (delta) => pushPullHandlersRef.current.preview(delta),
      onPushPullCommit: (delta) => pushPullHandlersRef.current.commit(delta),
      onPartMovePreview: (axis, delta) => partMoveHandlersRef.current.preview(axis, delta),
      onPartMoveCommit: (axis, delta) => partMoveHandlersRef.current.commit(axis, delta),
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
    const config = performanceConfig;
    const viewport = viewportRef.current;
    if (!config?.enabled || performanceReported.current || !viewport) return;
    if (!commands.length || !templates.length || !lessons.length) return;
    if (config.mode === "workload" && (!doc?.stats?.is_valid || !mesh || computing)) return;
    let cancelled = false;
    const report = async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      const navigation = config.mode === "workload"
        ? await viewport.measureNavigationFps(config.duration_ms)
        : null;
      if (cancelled) return;
      performanceReported.current = true;
      await backend.performanceReport({
        mode: config.mode,
        triangle_count: mesh?.triangle_count ?? 0,
        vertex_count: mesh?.vertex_count ?? 0,
        solid_count: doc?.stats?.solid_count ?? 0,
        viewport: {
          width: viewportEl.current?.clientWidth ?? 0,
          height: viewportEl.current?.clientHeight ?? 0,
          device_pixel_ratio: window.devicePixelRatio,
        },
        navigation,
        user_agent: navigator.userAgent,
      });
    };
    void report();
    return () => { cancelled = true; };
  }, [commands.length, computing, doc?.stats?.is_valid, doc?.stats?.solid_count,
    lessons.length, mesh, performanceConfig, templates.length]);

  useEffect(() => {
    const config = nativeE2eConfig;
    if (!config?.enabled || nativeE2eStarted.current) return;
    if (!commands.length || !templates.length || !lessons.length || !viewportRef.current) return;
    nativeE2eStarted.current = true;
    const fingerprint = (state: DocState) => JSON.stringify({
      doc_id: state.doc_id,
      document_instance_id: state.document_instance_id,
      revision: state.revision,
      parts: state.parts,
      operations: state.operations,
      history_len: state.history_len,
      history_index: state.history_index,
    });
    const run = async () => {
      try {
        const before = await backend.docGetState();
        const taskId = `native-${config.mode}-${Date.now()}`;
        const plan = backend.aiPlan("Создай шайбу 20×6×4 мм", taskId)
          .then((value) => ({ ok: true as const, value }))
          .catch((cause) => ({ ok: false as const, error: parseIpcError(cause) }));
        await new Promise((resolve) => window.setTimeout(resolve, config.cancel_delay_ms));
        const cancellation = await backend.aiCancel(taskId);
        const outcome = await plan;
        await new Promise((resolve) => window.setTimeout(resolve, 200));
        const after = await backend.docGetState();
        const recovery = config.mode === "ai-cad-cancel"
          ? await backend.docCreate("washer", { outer_diameter: 20, inner_diameter: 6, height: 4 })
          : null;
        await backend.nativeE2eReport({
          mode: config.mode,
          cancellation,
          outcome,
          state_unchanged: fingerprint(before) === fingerprint(after),
          before_revision: before.revision,
          after_revision: after.revision,
          recovery: recovery ? {
            revision: recovery.revision,
            is_valid: recovery.stats?.is_valid ?? false,
            solid_count: recovery.stats?.solid_count ?? 0,
          } : null,
        });
      } catch (cause) {
        await backend.nativeE2eReport({
          mode: config.mode,
          probe_error: parseIpcError(cause),
        });
      }
    };
    void run();
  }, [commands.length, lessons.length, nativeE2eConfig, templates.length]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.setEdgeSelectionMode(edgeTool.active, doc?.stats?.edges ?? []);
    if (edgeTool.selected) {
      const label = edgeTool.active ? `${edgeTool.kind === "fillet" ? "R" : "C"}${edgeTool.size} мм` : "Ребро";
      viewport.setEdgeMarker(edgeTool.selected, label);
    } else {
      viewport.setEdgeMarker(null);
    }
  }, [edgeTool.active, edgeTool.kind, edgeTool.selected, edgeTool.size, doc?.stats?.edges, mesh]);

  useEffect(() => {
    viewportRef.current?.setEditingEnabled(!computing && !geometryBusy && !meshLoading);
  }, [computing, geometryBusy, meshLoading]);

  useEffect(() => {
    document.body.classList.toggle("what-is-this", whatIsThis);
  }, [whatIsThis]);

  // ---------- работа с документом ----------
  const applyDoc = useCallback((state: DocState) => {
    const cur = docRef.current;
    // страж устаревших ответов: та же пара doc_id+slot, но меньшая ревизия
    if (cur && cur.slot === state.slot && cur.doc_id === state.doc_id && state.revision < cur.revision) return;
    if (cur && (cur.revision !== state.revision || cur.doc_id !== state.doc_id || cur.slot !== state.slot)) {
      setSelectedFace(null);
      viewportRef.current?.setSelectedFace(null);
      setEdgeTool((current) => ({ ...current, active: false, selected: null, partId: null }));
      viewportRef.current?.setSplitPreview(null);
    }
    setDoc(state);
    const token = ++meshToken.current;
    if (state.stats && (state.stats.is_valid || state.stats.mesh_mode)) {
      setMeshLoading(true);
      setComputing(true);
      backend.docGetMesh()
        .then((m) => {
          if (token === meshToken.current) {
            setMesh(m);
            setImportedStats(null); // снова показываем параметрическую модель
          }
        })
        .catch(() => {})
        .finally(() => {
          if (token === meshToken.current) { setComputing(false); setMeshLoading(false); }
        });
    } else {
      setMesh(null);
      setMeshLoading(false);
    }
  }, []);

  const beginGeometryOperation = useCallback(() => {
    geometryOperationCount.current += 1;
    setGeometryBusy(true);
  }, []);

  const endGeometryOperation = useCallback(() => {
    geometryOperationCount.current = Math.max(0, geometryOperationCount.current - 1);
    if (geometryOperationCount.current === 0) setGeometryBusy(false);
  }, []);

  const runBackend = useCallback(async (
    fn: () => Promise<DocState>,
    cancellable = false,
  ): Promise<DocState | null> => {
    if (documentActionPending.current || geometryOperationCount.current > 0) return null;
    documentActionPending.current = true;
    setComputing(true);
    if (cancellable) beginGeometryOperation();
    try {
      const state = await fn();
      applyDoc(state);
      return state;
    } catch (e) {
      const err = e as GeoError;
      setStatusMsg(`Ошибка: ${err.message ?? String(e)}`);
      return null;
    } finally {
      documentActionPending.current = false;
      if (cancellable) endGeometryOperation();
      setComputing(false);
    }
  }, [applyDoc, beginGeometryOperation, endGeometryOperation]);

  const cancelGeometry = useCallback(async () => {
    if (!geometryBusy || geometryCancelling) return;
    setGeometryCancelling(true);
    try {
      const result = await backend.geometryCancel();
      setStatusMsg(result.cancelled
        ? "Останавливаем вычисление; подтверждённая модель сохранена"
        : "Активное вычисление уже завершилось");
    } catch (error) {
      setStatusMsg(`Не удалось отменить вычисление: ${parseIpcError(error).message}`);
    } finally {
      setGeometryCancelling(false);
    }
  }, [geometryBusy, geometryCancelling]);

  // ---------- уроки ----------
  const persistProgress = (run: LessonRun) => {
    localStorage.setItem(lessonKey(run.lesson.lesson_id, run.lesson.content_version), JSON.stringify(run.statuses));
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
    if (!run || run.paused) return;
    const matches = (check: (typeof run.lesson.steps)[number]["check"]): boolean => {
      switch (check.type) {
        case "camera_rotated": return ev.type === "camera_rotated";
        case "camera_zoomed": return ev.type === "camera_zoomed";
        case "command": return ev.type === "command" && ev.command_id === check.command_id;
        case "face_selected": return ev.type === "face_selected";
        case "params": return ev.state != null && checkParams(check, ev.state);
        case "saved": return ev.type === "saved";
        case "reopened": return ev.type === "reopened" && (!check.params || (ev.state != null && checkParams(check, ev.state)));
        case "exported": return ev.type === "exported";
        case "operation":
          return ev.type === "operation" && ev.op === check.op
            && (check.radius == null || Math.abs((ev.radius ?? -1) - check.radius) < 1e-9);
        case "error_shown": return ev.type === "error_shown" && (!check.code || ev.code === check.code);
        case "imported": return ev.type === "imported" && (!check.mode || ev.mode === check.mode);
        case "check_result":
          return ev.type === "check_result"
            && (ev.checks ?? []).some((c) => c.id === check.id && c.status === check.status);
        default: return false;
      }
    };
    // событие может закрыть несколько подряд идущих уже выполненных шагов
    let cur = run;
    let progressed = false;
    while (cur.stepIndex < cur.lesson.steps.length
           && matches(cur.lesson.steps[cur.stepIndex].check)) {
      const statuses = [...cur.statuses];
      statuses[cur.stepIndex] = "done";
      cur = advanceIfDone({ ...cur, statuses });
      progressed = true;
    }
    if (progressed) setLessonRun(cur);
  }, [advanceIfDone, checkParams]);

  const undoDocument = useCallback(async () => {
    const state = await runBackend(() => backend.docUndo());
    if (!state) return;
    setStatusMsg("Последняя операция отменена");
    lessonEvent({ type: "command", command_id: "op.undo" });
  }, [runBackend, lessonEvent]);

  const redoDocument = useCallback(async () => {
    const state = await runBackend(() => backend.docRedo());
    if (!state) return;
    setStatusMsg("Операция повторена");
    lessonEvent({ type: "command", command_id: "op.redo" });
  }, [runBackend, lessonEvent]);

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
      if (lessonId === "navigation" || lessonId === "save-export") {
        state = await backend.docCreate("box", { length: 40, width: 30, height: 20 });
        applyDoc(state);
      }
      const statuses = loadLessonProgress(lesson.lesson_id, lesson.steps.length, lesson.content_version).map(() => "pending" as StepStatus);
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
    const statuses = loadLessonProgress(lessonId, lesson.steps.length, lesson.content_version);
    return statuses.every((s) => s !== "pending");
  }, [lessons]);

  // ---------- команды документа ----------
  const createFromTemplate = useCallback(async (t: TemplateDef, params?: Record<string, number>) => {
    const state = await runBackend(() => backend.docCreate(t.template_id, params), true);
    if (state) lessonEvent({ type: "params", state });
  }, [runBackend, lessonEvent]);

  // совместимость с уроком «Первая деталь»: создание учебной пластины
  const createPlate = useCallback(async () => {
    const state = await runBackend(() => backend.docCreatePlate({ length: 80, width: 40, height: 6, hole_diameter: 4, hole_offset: 10 }), true);
    if (state) lessonEvent({ type: "params", state });
  }, [runBackend, lessonEvent]);

  const applyField = useCallback(async (name: string, raw: string, partId?: string) => {
    const cur = docRef.current;
    if (!cur) return;
    const part = partId ? cur.parts?.find((p) => p.part_id === partId) : cur.parts?.[0];
    let num: number;
    try { num = evalExpression(raw, { ...(part?.params ?? cur.params) }); }
    catch (e) { setStatusMsg(`Ошибка выражения: ${(e as Error).message}`); return; }
    const state = await runBackend(() => backend.docSetParameter(name, num, raw, partId), true);
    if (state) lessonEvent({ type: "params", state });
  }, [runBackend, lessonEvent]);

  const cancelPushPull = useCallback(() => {
    const target = pushPullRef.current.target;
    viewportRef.current?.cancelPushPullPreview();
    setPushPull((current) => ({
      ...current,
      value: target ? String(target.current) : "",
      dragging: false,
    }));
  }, []);

  const commitPushPullValue = useCallback(async (value: number) => {
    const target = pushPullRef.current.target;
    if (!target) return;
    if (!Number.isFinite(value)) {
      setStatusMsg("Размер должен быть числом");
      return;
    }
    if (value < target.minimum) {
      setStatusMsg(`${target.label}: минимальное значение ${target.minimum} мм`);
      return;
    }
    viewportRef.current?.cancelPushPullPreview();
    setPushPull((current) => ({ ...current, value: String(value), dragging: false }));
    if (Math.abs(value - target.current) < 1e-9) return;
    const state = await runBackend(() => target.mode === "offset" && target.faceRef
      ? backend.docFaceOffset({ target_id: target.partId, face_ref: target.faceRef, distance: value })
      : backend.docSetParameter(target.parameter, value, String(value), target.partId), true);
    if (state && !state.error) {
      setStatusMsg(`${target.label}: ${value} мм`);
      if (target.mode === "offset") lessonEvent({ type: "operation", op: "face_offset" });
      else lessonEvent({ type: "params", state });
    }
  }, [runBackend, lessonEvent]);

  const previewPushPull = useCallback((delta: number) => {
    const target = pushPullRef.current.target;
    if (!target) return;
    const value = pushPullValue(target, delta);
    viewportRef.current?.setPushPullPreview(pushPullDelta(target, value));
    setPushPull((current) => ({ ...current, value: String(value), dragging: true }));
  }, []);

  const commitPushPullDelta = useCallback((delta: number) => {
    const target = pushPullRef.current.target;
    if (!target) return;
    void commitPushPullValue(pushPullValue(target, delta));
  }, [commitPushPullValue]);

  const updatePushPullValue = useCallback((raw: string) => {
    setPushPull((current) => ({ ...current, value: raw, dragging: false }));
    const target = pushPullRef.current.target;
    const value = parseMillimeters(raw);
    if (target && value != null && value >= target.minimum) {
      viewportRef.current?.setPushPullPreview(pushPullDelta(target, value));
    } else {
      viewportRef.current?.cancelPushPullPreview();
    }
  }, []);

  const applyPushPull = useCallback(() => {
    const value = parseMillimeters(pushPullRef.current.value);
    if (value != null) void commitPushPullValue(value);
    else setStatusMsg("Введите размер в миллиметрах");
  }, [commitPushPullValue]);

  pushPullHandlersRef.current = {
    start: () => setPushPull((current) => ({ ...current, dragging: !!current.target })),
    preview: previewPushPull,
    commit: commitPushPullDelta,
  };

  useEffect(() => {
    const viewport = viewportRef.current;
    viewport?.setSelectedFace(selectedFace);
    if (selectedFace == null || !mesh || !doc) {
      viewport?.setPushPullHandle(null);
      viewport?.setFaceFeaturePreview(null);
      viewport?.setFaceDomePreview(null);
      viewport?.setSheetBendPreview(null);
      setPushPull({ target: null, value: "", dragging: false, reason: null });
      setFaceFeatureTarget(null);
      setSheetBendTarget(null);
      setFaceFeatureReason(null);
      return;
    }

    let reason: string | null = null;
    let target = null;
    let featureTarget: FaceFeatureTarget | null = null;
    let bendTarget: FaceFeatureTarget | null = null;
    let featureReason: string | null = null;
    const parts = doc.parts ?? [];
    if (importedStats) {
      reason = "Push/Pull для импортированной сетки пока недоступен.";
      featureReason = "Элементы на грани для импортированной сетки пока недоступны.";
    } else {
      const solidIndex = mesh.face_ranges
        .find((candidate) => candidate.face_index === selectedFace)?.solid_index;
      const liveParts = doc.stats?.parts ?? [];
      let selectedId = selectedPartId;
      if (solidIndex != null) {
        let firstSolid = 0;
        for (const livePart of liveParts) {
          const nextSolid = firstSolid + livePart.solid_count;
          if (solidIndex >= firstSolid && solidIndex < nextSolid) {
            selectedId = livePart.part_id;
            break;
          }
          firstSolid = nextSolid;
        }
      }
      const part = parts.find((candidate) => candidate.part_id === selectedId);
      if (!selectedId) {
        reason = "Не удалось определить выбранное тело. Выберите его заново.";
        featureReason = reason;
      } else {
        const solidIndices = solidIndicesForParts(liveParts, [selectedId]);
        featureTarget = resolveFaceFeatureTarget(mesh, selectedFace, selectedId, solidIndices);
        bendTarget = resolveSheetBendTarget(mesh, selectedFace, selectedId, solidIndices);
        if (!featureTarget) {
          featureReason = "Выберите внешнюю плоскую грань на границе детали.";
        }
        target = resolveGenericFaceEditTarget(mesh, selectedFace, selectedId, solidIndices);
        const template = part && templates.find((candidate) => candidate.template_id === part.template);
        const changesSelectedPartTopology = (doc.operations ?? []).some((operation) => {
          const operationTarget = operation.target_id ?? operation.part_id;
          return operationTarget === selectedId && operation.op !== "fillet" && operation.op !== "chamfer";
        });
        if (target) {
          reason = null;
        } else if (changesSelectedPartTopology) {
          reason = "Push/Pull недоступен после операций, меняющих топологию выбранного тела.";
        } else {
          if (part && template) target = resolveFaceEditTarget(mesh, selectedFace, part, template, solidIndices);
          if (!target) reason = "Смещение поддерживается для плоских граней. Выберите плоскую поверхность.";
        }
      }
    }

    viewport?.setPushPullHandle(moveMode ? null : target);
    setPushPull({
      target,
      value: target ? String(target.current) : "",
      dragging: false,
      reason,
    });
    setFaceFeatureTarget(featureTarget);
    setSheetBendTarget(bendTarget);
    setFaceFeatureReason(featureReason);
  }, [selectedFace, selectedPartId, mesh, doc, templates, importedStats, moveMode]);

  // сброс выбора детали, если она исчезла из живых тел
  useEffect(() => {
    const live = doc?.stats?.parts;
    if (!live) return;
    const liveIds = new Set(live.map((part) => part.part_id));
    setSelectedPartIds((current) => current.every((id) => liveIds.has(id)) ? current : current.filter((id) => liveIds.has(id)));
    if (selectedPartId && !liveIds.has(selectedPartId)) setSelectedPartId(null);
  }, [doc, selectedPartId]);

  useEffect(() => {
    const viewport = viewportRef.current;
    const liveParts = doc?.stats?.parts ?? [];
    if (!viewport || !mesh) {
      viewport?.setSelectedSolids([]);
      viewport?.setTransformHandle(null);
      return;
    }
    const selectedSolidIndices = solidIndicesForParts(liveParts, selectedPartId ? [selectedPartId] : []);
    viewport.setSelectedSolids(solidIndicesForParts(liveParts, selectedPartIds));
    viewport.setTransformHandle(moveMode && selectedPartId && selectedSolidIndices.length > 0
      ? { partId: selectedPartId, solidIndices: selectedSolidIndices }
      : null);
  }, [doc, mesh, selectedPartId, selectedPartIds, moveMode]);

  const activePartId = useCallback((): string | undefined => {
    const cur = docRef.current;
    const live = cur?.stats?.parts;
    if (selectedPartId && live?.some((p) => p.part_id === selectedPartId)) return selectedPartId;
    return live?.[0]?.part_id ?? cur?.parts?.[0]?.part_id;
  }, [selectedPartId]);

  const addPart = useCallback(async (t: TemplateDef) => {
    const state = await runBackend(() => backend.docAddPart(t.template_id), true);
    if (state && !state.error) {
      const parts = state.stats?.parts ?? [];
      const added = parts[parts.length - 1];
      if (added) {
        setSelectedPartId(added.part_id);
        setSelectedPartIds([added.part_id]);
        setMoveMode(true);
        setStatusMsg("Форма добавлена. Потяните цветную стрелку, чтобы поставить её на нужное место");
      }
    }
  }, [runBackend]);

  const runBoolean = useCallback(async (
    kind: "union" | "subtract" | "intersect",
    keepTool: boolean,
    explicitToolId?: string,
    explicitTargetId?: string,
  ) => {
    const live = docRef.current?.stats?.parts ?? [];
    if (live.length < 2) return;
    const target = live.find((p) => p.part_id === (explicitTargetId ?? selectedPartId)) ?? live[0];
    const tool = live.find((part) => part.part_id === explicitToolId) ??
      live[(live.indexOf(target) + 1) % live.length];
    if (tool.part_id === target.part_id) return;
    const state = await runBackend(() => backend.docBoolean(kind, target.part_id, tool.part_id, keepTool), true);
    if (state && !state.error) {
      setSelectedFace(null);
      viewportRef.current?.setSelectedFace(null);
      setSelectedPartId(target.part_id);
      setSelectedPartIds([target.part_id]);
      const labels = { union: "Детали объединены", subtract: "Инструмент вычтен", intersect: "Оставлено пересечение" };
      setStatusMsg(labels[kind]);
    }
  }, [runBackend, selectedPartId]);

  const runArray = useCallback(async (count: number, step: [number, number, number]) => {
    const id = activePartId();
    if (!id) return;
    await runBackend(() => backend.docArray(id, count, step), true);
  }, [runBackend, activePartId]);

  const runMirror = useCallback(async (plane: "XY" | "XZ" | "YZ") => {
    const id = activePartId();
    if (!id) return;
    await runBackend(() => backend.docMirror(id, plane), true);
  }, [runBackend, activePartId]);

  const runSplit = useCallback(async (plane: "XY" | "XZ" | "YZ", offset: number) => {
    const id = activePartId();
    if (!id) return;
    const state = await runBackend(() => backend.docSplit(id, plane, offset), true);
    if (state && !state.error) {
      setSelectedFace(null);
      viewportRef.current?.setSelectedFace(null);
      setSelectedPartId(id);
      setStatusMsg(`Деталь разделена плоскостью ${plane} на отметке ${offset} мм`);
    }
  }, [runBackend, activePartId]);

  const runTransform = useCallback(async (translate: [number, number, number]) => {
    const id = activePartId();
    if (!id) return;
    const state = await runBackend(() => backend.docTransform(id, translate), true);
    viewportRef.current?.cancelTransformPreview();
    setMovePreview(null);
    if (state && !state.error) {
      const [x, y, z] = translate;
      setStatusMsg(`Деталь перемещена: X ${x} мм, Y ${y} мм, Z ${z} мм`);
      lessonEvent({ type: "operation", op: "transform" });
    }
  }, [runBackend, activePartId, lessonEvent]);

  partMoveHandlersRef.current = {
    preview: (axis, delta) => setMovePreview({ axis, delta }),
    commit: (axis, delta) => {
      const translate: [number, number, number] = [0, 0, 0];
      translate[axis === "x" ? 0 : axis === "y" ? 1 : 2] = delta;
      void runTransform(translate);
    },
  };

  const runProfileExtrude = useCallback(async (args: Parameters<typeof backend.docProfileExtrude>[0]) => {
    await runBackend(() => backend.docProfileExtrude(args), true);
  }, [runBackend]);

  const runSketchExtrude = useCallback(async (args: SketchExtrudeArgs) => {
    const state = await runBackend(() => backend.docSketchExtrude(args), true);
    if (state && !state.error) lessonEvent({ type: "operation", op: "sketch_extrude" });
  }, [runBackend, lessonEvent]);

  const runSketchSolve = useCallback(async (sketch: ConstrainedSketch) => {
    setComputing(true);
    beginGeometryOperation();
    try {
      const solution = await backend.sketchSolve(sketch);
      setConstraintSolution(solution);
      setStatusMsg(solution.degrees_of_freedom === 0
        ? "Эскиз полностью определён"
        : `Эскиз недоопределён: ${solution.degrees_of_freedom} DOF`);
      lessonEvent({ type: "command", command_id: "op.sketch.solve" });
    } catch (error) {
      setConstraintSolution(null);
      setStatusMsg(`Ошибка решателя: ${parseIpcError(error).message}`);
    } finally {
      endGeometryOperation();
      setComputing(false);
    }
  }, [beginGeometryOperation, endGeometryOperation, lessonEvent]);

  const runConstrainedSketchExtrude = useCallback(async (args: ConstrainedSketchExtrudeArgs) => {
    const state = await runBackend(() => backend.docConstrainedSketchExtrude(args), true);
    if (state && !state.error) lessonEvent({ type: "operation", op: "constrained_sketch_extrude" });
  }, [runBackend, lessonEvent]);

  const runRevolve = useCallback(async (args: RevolveArgs) => {
    await runBackend(() => backend.docRevolve(args), true);
  }, [runBackend]);

  const runSweep = useCallback(async (args: SweepArgs) => {
    await runBackend(() => backend.docSweep(args), true);
  }, [runBackend]);

  const runLoft = useCallback(async (args: LoftArgs) => {
    await runBackend(() => backend.docLoft(args), true);
  }, [runBackend]);

  const runShell = useCallback(async (args: ShellArgs) => {
    const state = await runBackend(() => backend.docShell(args), true);
    if (state && !state.error) lessonEvent({ type: "operation", op: "shell" });
  }, [runBackend, lessonEvent]);

  const runDraftPrism = useCallback(async (args: DraftPrismArgs) => {
    await runBackend(() => backend.docDraftPrism(args), true);
  }, [runBackend]);

  const runRib = useCallback(async (args: RibArgs) => {
    await runBackend(() => backend.docRib(args), true);
  }, [runBackend]);

  const runFitPocket = useCallback(async (args: FitPocketArgs) => {
    await runBackend(() => backend.docFitPocket(args), true);
  }, [runBackend]);

  const runVectorExtrude = useCallback(async (args: VectorExtrudeArgs) => {
    await runBackend(() => backend.docVectorExtrude({ ...args, path: expandTilde(args.path) }), true);
  }, [runBackend]);

  const runTextRelief = useCallback(async (args: TextReliefArgs) => {
    await runBackend(() => backend.docTextRelief(args), true);
  }, [runBackend]);

  const runThreadPair = useCallback(async (args: ThreadPairArgs) => {
    await runBackend(() => backend.docThreadPair(args), true);
  }, [runBackend]);

  const runClearanceCalibration = useCallback(async (args: ClearanceCalibrationArgs) => {
    await runBackend(() => backend.docClearanceCalibration(args), true);
  }, [runBackend]);

  const runSplitConnectorPair = useCallback(async (args: SplitConnectorPairArgs) => {
    await runBackend(() => backend.docSplitConnectorPair(args), true);
  }, [runBackend]);

  const previewFaceFeature = useCallback((preview: FaceFeaturePreview | null) => {
    viewportRef.current?.setFaceFeaturePreview(preview);
  }, []);

  const runFaceFeature = useCallback(async (args: FaceFeatureArgs) => {
    viewportRef.current?.setFaceFeaturePreview(null);
    const state = await runBackend(() => backend.docFaceFeature(args), true);
    if (!state || state.error) return;
    setSelectedFace(null);
    viewportRef.current?.setSelectedFace(null);
    setStatusMsg(args.mode === "add" ? "Выдавливание на грани создано" : "Вырез на грани создан");
  }, [runBackend]);

  const previewFaceDome = useCallback((preview: FaceDomePreview | null) => {
    viewportRef.current?.setFaceDomePreview(preview);
  }, []);

  const runFaceDome = useCallback(async (args: FaceDomeArgs) => {
    viewportRef.current?.setFaceDomePreview(null);
    const state = await runBackend(() => backend.docFaceDome(args), true);
    if (!state || state.error) return;
    setSelectedFace(null);
    viewportRef.current?.setSelectedFace(null);
    setStatusMsg(args.mode === "add" ? "Выпуклость создана" : "Вмятина создана");
  }, [runBackend]);

  const previewSheetBend = useCallback((preview: SheetBendPreview | null) => {
    viewportRef.current?.setSheetBendPreview(preview);
  }, []);

  const runSheetBend = useCallback(async (args: SheetBendArgs) => {
    viewportRef.current?.setSheetBendPreview(null);
    const state = await runBackend(() => backend.docSheetBend(args), true);
    if (!state || state.error) return;
    setSelectedFace(null);
    viewportRef.current?.setSelectedFace(null);
    setStatusMsg(`Изгиб ${args.angle}° создан`);
  }, [runBackend]);

  const runArrayCircular = useCallback(async (count: number, angle: number, center: [number, number, number]) => {
    const id = activePartId();
    if (!id) return;
    await runBackend(() => backend.docArrayCircular(id, count, angle, center), true);
  }, [runBackend, activePartId]);

  const runAlign = useCallback(async (axis: "x" | "y" | "z", align: "center" | "min" | "max", value: number) => {
    const id = activePartId();
    if (!id) return;
    await runBackend(() => backend.docAlign(id, axis, align, value), true);
  }, [runBackend, activePartId]);

  // ---------- измерения ----------
  const runMeasure = useCallback(async () => {
    setMeasureBusy(true);
    beginGeometryOperation();
    try {
      const bboxRes = await backend.measure({ type: "bbox" });
      const volRes = await backend.measure({ type: "volume" });
      setMeasureResult((prev) => ({
        ...prev,
        source: (bboxRes.source as string) ?? "brep",
        bbox: (bboxRes.bbox as number[]) ?? (bboxRes.min && bboxRes.max ? [...(bboxRes.min as number[]), ...(bboxRes.max as number[])] as number[] : undefined),
        volume: volRes.volume as number | undefined,
        faceError: undefined,
      }));
    } catch (e) {
      setStatusMsg(`Ошибка измерения: ${parseIpcError(e).message}`);
    } finally {
      endGeometryOperation();
      setMeasureBusy(false);
    }
  }, [beginGeometryOperation, endGeometryOperation]);

  const runMeasureFace = useCallback(async () => {
    if (selectedFace == null) return;
    setMeasureBusy(true);
    beginGeometryOperation();
    try {
      const res = await backend.measure({ type: "face_diameter", face_index: selectedFace });
      setMeasureResult((prev) => ({ ...prev, faceDiameter: res.diameter as number | undefined, faceError: undefined }));
    } catch (e) {
      const err = parseIpcError(e);
      setMeasureResult((prev) => ({ ...prev, faceDiameter: undefined, faceError: err.message }));
    } finally {
      endGeometryOperation();
      setMeasureBusy(false);
    }
  }, [selectedFace, beginGeometryOperation, endGeometryOperation]);

  const runMeasureDistance = useCallback(async (p0: [number, number, number], p1: [number, number, number]) => {
    setMeasureBusy(true);
    beginGeometryOperation();
    try {
      const res = await backend.measure({ type: "distance", p0, p1 });
      setMeasureResult((prev) => ({ ...prev, distance: res.distance as number | undefined }));
    } catch (e) {
      setStatusMsg(`Ошибка измерения: ${parseIpcError(e).message}`);
    } finally {
      endGeometryOperation();
      setMeasureBusy(false);
    }
  }, [beginGeometryOperation, endGeometryOperation]);

  // ---------- обработка рёбер ----------
  const startEdgeTool = useCallback((kind: EdgeFeatureKind) => {
    setMoveMode(false);
    setMovePreview(null);
    viewportRef.current?.setTransformHandle(null);
    setEdgeTool((current) => ({ ...current, active: true, kind }));
    setSelectedFace(null);
    viewportRef.current?.setSelectedFace(null);
  }, []);

  const cancelEdgeTool = useCallback(() => {
    setEdgeTool((current) => ({ ...current, active: false, selected: null, partId: null }));
    viewportRef.current?.setEdgeSelectionMode(false, docRef.current?.stats?.edges ?? []);
    viewportRef.current?.setEdgeMarker(null);
  }, []);

  const selectEdge = useCallback((e: EdgeRef) => {
    const liveParts = docRef.current?.stats?.parts ?? [];
    const edgePartId = partIdForSolid(liveParts, e.solid_index);
    setSelectedFace(null);
    viewportRef.current?.setSelectedFace(null);
    if (edgePartId) { setSelectedPartId(edgePartId); setSelectedPartIds([edgePartId]); }
    setEdgeTool((current) => ({
      ...current,
      selected: e,
      partId: edgePartId ?? activePartId() ?? null,
    }));
  }, [activePartId]);
  edgeSelectHandlerRef.current = selectEdge;

  const applyEdgeTool = useCallback(async () => {
    const current = edgeToolRef.current;
    if (!current.selected) return;
    const size = parseMillimeters(current.size);
    if (size == null || size <= 0) {
      setStatusMsg(current.kind === "fillet"
        ? "Радиус должен быть положительным числом"
        : "Размер фаски должен быть положительным числом");
      return;
    }
    const state = await runBackend(() => current.kind === "fillet"
      ? backend.docFillet(current.selected!, size, current.partId ?? activePartId())
      : backend.docChamfer(current.selected!, size, current.partId ?? activePartId()), true);
    if (state && !state.error) {
      cancelEdgeTool();
      setStatusMsg(current.kind === "fillet" ? "Скругление создано" : "Фаска создана");
      if (current.kind === "fillet") {
        lessonEvent({ type: "operation", op: "fillet", radius: size });
      }
    }
  }, [runBackend, cancelEdgeTool, lessonEvent, activePartId]);

  const clearErrorOrUndo = useCallback(() => {
    const code = docRef.current?.error?.code;
    if (code === "fillet_failed" || code === "chamfer_failed" || code === "dome_failed" ||
        code === "bend_failed" || code === "face_offset_failed" || code === "split_failed" || code === "unsupported_face" || code === "bad_ref" ||
        code === "reselect_required") {
      void runBackend(() => backend.docClearError());
    } else {
      void undoDocument();
    }
  }, [runBackend, undoDocument]);

  // ---------- проверка печати ----------
  const runPrintCheck = useCallback(async (printer: { x: number; y: number; z: number }) => {
    setPrintBusy(true);
    beginGeometryOperation();
    try {
      const res = await backend.printCheck(printer);
      setPrintChecks(res.checks ?? []);
      lessonEvent({ type: "check_result", checks: res.checks ?? [] });
    } catch (e) {
      setStatusMsg(`Ошибка проверки: ${parseIpcError(e).message}`);
    } finally {
      endGeometryOperation();
      setPrintBusy(false);
    }
  }, [beginGeometryOperation, endGeometryOperation]);

  // ---------- импорт ----------
  const runImport = useCallback(async (path: string, format: "step" | "stl", unitScale?: number) => {
    setImportBusy(true);
    beginGeometryOperation();
    try {
      const res = await backend.docImport(expandTilde(path), format, unitScale);
      if (format === "stl" && unitScale === undefined) {
        // первый проход: показываем габарит и спрашиваем единицы
        setImportPreview(res);
      } else {
        const meshData = await backend.docGetImportedMesh(res.mesh);
        setMesh(meshData);
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
      endGeometryOperation();
      setImportBusy(false);
    }
  }, [beginGeometryOperation, endGeometryOperation]);

  const applyMeshImport = useCallback(async (path: string, unitScale: number) => {
    const state = await runBackend(() => backend.docMeshImportApply(expandTilde(path), "stl", unitScale), true);
    if (state && !state.error) {
      setImportPreview(null);
      setStatusMsg(`Mesh применён к документу: ${expandTilde(path)}`);
      lessonEvent({ type: "operation", op: "mesh_source" });
    }
  }, [runBackend, lessonEvent]);

  const runMeshTransform = useCallback(async (translate: [number, number, number], scale: number) => {
    await runBackend(() => backend.docMeshTransform(translate, [0, 0, 0], scale), true);
  }, [runBackend]);

  const runMeshRepair = useCallback(async () => {
    const state = await runBackend(() => backend.docMeshRepair(), true);
    if (state && !state.error) lessonEvent({ type: "operation", op: "mesh_repair" });
  }, [runBackend, lessonEvent]);

  const runMeshDecimate = useCallback(async (targetRatio: number) => {
    const state = await runBackend(() => backend.docMeshDecimate(targetRatio), true);
    if (state && !state.error) lessonEvent({ type: "operation", op: "mesh_decimate" });
  }, [runBackend, lessonEvent]);

  const previewImageRelief = useCallback(async (settings: ImageReliefSettings) => {
    setComputing(true);
    beginGeometryOperation();
    try {
      const preview = await backend.imageReliefPreview({
        ...settings, path: expandTilde(settings.path),
      });
      const previewMesh = await backend.docGetImportedMesh(preview.mesh);
      setMesh(previewMesh);
      setImportedStats(preview.stats);
      setImageReliefPreview(preview);
      setStatusMsg("Decorative mesh preview готов; документ не изменён");
      lessonEvent({ type: "command", command_id: "op.image_relief.preview" });
    } catch (error) {
      setImageReliefPreview(null);
      setStatusMsg(`Ошибка image relief: ${parseIpcError(error).message}`);
    } finally {
      endGeometryOperation();
      setComputing(false);
    }
  }, [beginGeometryOperation, endGeometryOperation, lessonEvent]);

  const applyImageRelief = useCallback(async (
    settings: ImageReliefSettings, expectedSha256: string,
  ) => {
    const state = await runBackend(() => backend.docImageReliefApply({
      ...settings, path: expandTilde(settings.path),
    }, expectedSha256), true);
    if (state && !state.error) {
      setImageReliefPreview(null);
      setStatusMsg("Decorative mesh применён одной транзакцией");
      lessonEvent({ type: "operation", op: "image_relief_source" });
    }
  }, [runBackend, lessonEvent]);

  const cancelImageReliefPreview = useCallback(() => {
    setImageReliefPreview(null);
    setImportedStats(null);
    const current = docRef.current;
    if (current?.stats) applyDoc(current);
    else setMesh(null);
    setStatusMsg("Decorative mesh preview отменён; документ не изменён");
  }, [applyDoc]);

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
    beginGeometryOperation();
    try {
      const res = await backend.docExport(path, format);
      const kb = (res.bytes / 1024).toFixed(1);
      const volume = res.stats.volume;
      const volumeText = volume == null ? "объём неизвестен" : `объём ${Math.round(volume * 10) / 10} мм³`;
      setStatusMsg(`Экспортировано: ${res.path} — ${kb} КБ, ${volumeText}`);
      lessonEvent({ type: "exported" });
    } catch (e) {
      setStatusMsg(`Ошибка экспорта: ${parseIpcError(e).message}`);
    } finally {
      endGeometryOperation();
      setComputing(false);
    }
  }, [exportPath, lessonEvent, beginGeometryOperation, endGeometryOperation]);

  const viewCommand = useCallback((id: string) => {
    const vp = viewportRef.current;
    if (!vp) return;
    if (id === "view.fit") vp.fit();
    else if (id === "view.proj") vp.toggleProjection();
    else vp.setView(id.replace("view.", "") as ViewName);
    lessonEvent({ type: "command", command_id: id });
  }, [lessonEvent]);

  const openHelpArticle = useCallback((helpId: string) => {
    setAiOpen(false);
    setHelpOpen(true);
    setArticleReq((r) => ({ helpId, seq: (r?.seq ?? 0) + 1 }));
  }, []);

  const applyAiPlan = useCallback(async (
    operations: AiOperation[],
    baseRevision: number,
    documentInstanceId: string | number,
    planHash: string,
    actionId: string,
  ): Promise<number | null> => {
    const state = await runBackend(() => backend.docTransaction({
      operations,
      base_revision: baseRevision,
      document_instance_id: documentInstanceId,
      plan_hash: planHash,
      action_id: actionId,
      mode: "apply",
    }), true);
    if (!state || state.error) return null;
    lessonEvent({ type: "params", state });
    setStatusMsg("AI-план применён одной транзакцией");
    return state.revision;
  }, [runBackend, lessonEvent]);

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
    if (template) {
      void (docRef.current?.stats?.parts?.length ? addPart(template) : createFromTemplate(template));
      return;
    }
    switch (id) {
      case "op.undo": void undoDocument(); break;
      case "op.redo": void redoDocument(); break;
      case "doc.save": void doSave(); break;
      case "doc.open": void doOpen(); break;
      case "export.stl": void doExport("stl"); break;
      case "export.step": void doExport("step"); break;
      case "export.3mf": void doExport("3mf"); break;
      case "op.fillet": startEdgeTool("fillet"); break;
      case "op.chamfer": startEdgeTool("chamfer"); break;
      case "op.face_offset":
        setMoveMode(false);
        cancelEdgeTool();
        setStatusMsg("Выберите плоскую грань и задайте смещение прямо под сценой");
        document.querySelector<HTMLInputElement>('[aria-label="Смещение грани, мм"]')?.focus();
        break;
      case "ai.panel.open": setHelpOpen(false); setAiOpen((v) => !v); break;
      case "app.help.open": setAiOpen(false); setHelpOpen((v) => !v); break;
      case "app.help.what_is_this": setWhatIsThis((v) => !v); break;
    }
  }, [commands, templates, createFromTemplate, addPart, undoDocument, redoDocument, doSave, doOpen, doExport, startEdgeTool, cancelEdgeTool]);

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
          if (docRef.current?.can_redo) void redoDocument();
        } else if (docRef.current?.can_undo) {
          void undoDocument();
        }
      } else if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (docRef.current) void doSave();
      } else if (mod && e.key.toLowerCase() === "o") {
        e.preventDefault();
        void doOpen();
      } else if (mod && e.key === "/") {
        e.preventDefault();
        setAiOpen(false);
        setHelpOpen((v) => !v);
      } else if (e.key === "Escape" && e.shiftKey) {
        e.preventDefault();
        setWhatIsThis((v) => !v);
      } else if (e.key === "Escape") {
        const pushPullState = pushPullRef.current;
        const pushPullValueNumber = Number(pushPullState.value.replace(",", "."));
        const pushPullPending = pushPullState.dragging || (
          pushPullState.target != null &&
          Number.isFinite(pushPullValueNumber) &&
          Math.abs(pushPullValueNumber - pushPullState.target.current) >= 1e-9
        );
        if (pushPullPending) cancelPushPull();
        else if (edgeToolRef.current.active) cancelEdgeTool();
        else if (moveMode) {
          viewportRef.current?.cancelTransformPreview();
          setMoveMode(false); setMovePreview(null);
        }
        else if (whatIsThis) setWhatIsThis(false);
        else if (aiOpen) setAiOpen(false);
        else if (helpOpen) setHelpOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [whatIsThis, helpOpen, aiOpen, moveMode, undoDocument, redoDocument, doSave, doOpen, cancelEdgeTool, cancelPushPull]);

  const faceAreaValue = mesh && selectedFace != null ? faceArea(mesh, selectedFace) : null;
  const docName = doc?.path ? doc.path.split("/").pop()! : "Без названия";
  const hasBody = (!!doc?.stats?.is_valid || !!doc?.stats?.mesh_mode || !!importedStats) && !!mesh;
  const sceneParts = (doc?.stats?.parts ?? [])
    .map((part, index) => ({ part_id: part.part_id, name: `${index + 1}. ${part.name}` }));
  const selectedPartName = sceneParts.find((part) => part.part_id === selectedPartId)?.name ?? null;
  const splitCenter = React.useMemo(() => selectedBoundsCenter(mesh,
    solidIndicesForParts(doc?.stats?.parts ?? [], selectedPartId ? [selectedPartId] : [])), [mesh, doc, selectedPartId]);
  const splitDefaults = { YZ: splitCenter[0], XZ: splitCenter[1], XY: splitCenter[2] };
  const showFaceActions = () => {
    const panel = document.querySelector<HTMLElement>(".face-info");
    panel?.scrollIntoView({ behavior: "smooth", block: "start" });
    panel?.classList.add("context-highlight");
    window.setTimeout(() => panel?.classList.remove("context-highlight"), 1200);
  };

  return (
    <div className="app-shell">
      <TopBar commands={commands} doc={doc} docName={docName} onCommand={runCommand} />
      <div className="app-main">
        <LeftPanel
          doc={doc}
          templates={templates}
          importedStats={importedStats}
          selectedPartId={selectedPartId}
          selectedPartIds={selectedPartIds}
          onSelectPart={(partId, additive = false) => {
            cancelEdgeTool(); cancelPushPull();
            setSelectedFace(null);
            const next = togglePartSelection(selectedPartIdsRef.current, partId, additive);
            setSelectedPartId(next[next.length - 1] ?? null);
            setSelectedPartIds(next);
          }}
          onCreateTemplate={(t) => void (hasBody ? addPart(t) : createFromTemplate(t))}
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
          {hasBody && (
            <PrimitivePicker templates={templates} onCreate={(template) => void addPart(template)} />
          )}
          {!hasBody && !computing && (
            <EmptyState
              templates={templates}
              onCreateTemplate={(t) => void createFromTemplate(t)}
              onLesson={() => void startLesson("first-part")}
            />
          )}
          <div className="scene-dock">
          <SelectionCoach
            key={`${doc?.doc_id}:${doc?.slot}:${doc?.revision}:${selectedPartId}`}
            hasBody={hasBody}
            busy={computing || geometryBusy || meshLoading}
            selectedFace={selectedFace}
            faceArea={faceAreaValue}
            canAddFaceFeature={faceFeatureTarget != null}
            selectedPartName={selectedPartName}
            selectedPartId={selectedPartId}
            selectedPartIds={selectedPartIds}
            pushPull={pushPull}
            edgeTool={edgeTool}
            moveMode={moveMode}
            movePreview={movePreview}
            parts={sceneParts}
            splitDefaults={splitDefaults}
            onStartEdgeTool={startEdgeTool}
            onStartMove={() => {
              cancelEdgeTool();
              cancelPushPull();
              setSelectedPartIds(selectedPartId ? [selectedPartId] : []);
              setMoveMode(true);
              setMovePreview(null);
            }}
            onCancelMove={() => {
              viewportRef.current?.cancelTransformPreview();
              viewportRef.current?.setTransformHandle(null);
              setMoveMode(false);
              setMovePreview(null);
            }}
            onMoveExact={(axis, delta) => partMoveHandlersRef.current.commit(axis, delta)}
            onMovePreview={(axis, delta) => {
              viewportRef.current?.setTransformPreview(axis, delta);
              setMovePreview({ axis, delta });
            }}
            onBoolean={(kind, targetId, toolId, keepTool) => void runBoolean(kind, keepTool, toolId, targetId)}
            onSplit={(plane, offset) => void runSplit(plane, offset)}
            onSplitPreview={(plane, offset) => viewportRef.current?.setSplitPreview(plane, offset,
              solidIndicesForParts(docRef.current?.stats?.parts ?? [], selectedPartId ? [selectedPartId] : []))}
            onPushPullValue={updatePushPullValue}
            onApplyPushPull={applyPushPull}
            onCancelPushPull={cancelPushPull}
            onEdgeToolSize={(size) => setEdgeTool((current) => ({ ...current, size }))}
            onApplyEdgeTool={() => void applyEdgeTool()}
            onCancelEdgeTool={cancelEdgeTool}
            onShowFaceActions={showFaceActions}
          />
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
          </div>
        </main>
        <ParamsPanel
          doc={doc}
          templates={templates}
          selectedFace={selectedFace}
          faceArea={faceAreaValue}
          pushPull={pushPull}
          faceFeatureTarget={faceFeatureTarget}
          sheetBendTarget={sheetBendTarget}
          faceFeatureReason={faceFeatureReason}
          onFaceFeaturePreview={previewFaceFeature}
          onApplyFaceFeature={(args) => void runFaceFeature(args)}
          onFaceDomePreview={previewFaceDome}
          onApplyFaceDome={(args) => void runFaceDome(args)}
          onSheetBendPreview={previewSheetBend}
          onApplySheetBend={(args) => void runSheetBend(args)}
          onPushPullValue={updatePushPullValue}
          onApplyPushPull={applyPushPull}
          onCancelPushPull={cancelPushPull}
          onApplyField={(n, r, p) => void applyField(n, r, p)}
          selectedPartId={selectedPartId}
          onAddPart={(t) => void addPart(t)}
          onBoolean={(k, keep) => void runBoolean(k, keep)}
          onArray={(c, s) => void runArray(c, s)}
          onMirror={(pl) => void runMirror(pl)}
          onSplit={(pl, off) => void runSplit(pl, off)}
          onTransform={(tr) => void runTransform(tr)}
          onProfileExtrude={(a) => void runProfileExtrude(a)}
          onSketchExtrude={(a) => void runSketchExtrude(a)}
          constraintSolution={constraintSolution}
          onSketchSolve={(sketch) => void runSketchSolve(sketch)}
          onConstrainedSketchExtrude={(a) => void runConstrainedSketchExtrude(a)}
          onRevolve={(a) => void runRevolve(a)}
          onSweep={(a) => void runSweep(a)}
          onLoft={(a) => void runLoft(a)}
          onShell={(a) => void runShell(a)}
          onDraftPrism={(a) => void runDraftPrism(a)}
          onRib={(a) => void runRib(a)}
          onFitPocket={(a) => void runFitPocket(a)}
          onVectorExtrude={(a) => void runVectorExtrude(a)}
          onTextRelief={(a) => void runTextRelief(a)}
          onThreadPair={(a) => void runThreadPair(a)}
          onClearanceCalibration={(a) => void runClearanceCalibration(a)}
          onSplitConnectorPair={(a) => void runSplitConnectorPair(a)}
          onArrayCircular={(c, ang, ctr) => void runArrayCircular(c, ang, ctr)}
          onAlign={(ax, al, v) => void runAlign(ax, al, v)}
          measureResult={measureResult}
          measureBusy={measureBusy}
          onMeasure={() => void runMeasure()}
          onMeasureFace={() => void runMeasureFace()}
          onMeasureDistance={(p0, p1) => void runMeasureDistance(p0, p1)}
          edgeTool={edgeTool}
          onStartEdgeTool={startEdgeTool}
          onSelectEdge={selectEdge}
          onEdgeToolKind={(kind) => setEdgeTool((current) => ({ ...current, kind }))}
          onEdgeToolSize={(size) => setEdgeTool((current) => ({ ...current, size }))}
          onApplyEdgeTool={() => void applyEdgeTool()}
          onCancelEdgeTool={cancelEdgeTool}
          onClearError={clearErrorOrUndo}
          printChecks={printChecks}
          printBusy={printBusy}
          onPrintCheck={(p) => void runPrintCheck(p)}
          importPreview={importPreview}
          importBusy={importBusy}
          onImport={(p, f, s) => void runImport(p, f, s)}
          onApplyMeshImport={(p, s) => void applyMeshImport(p, s)}
          onCancelImportPreview={() => setImportPreview(null)}
          onMeshTransform={(translate, scale) => void runMeshTransform(translate, scale)}
          onMeshRepair={() => void runMeshRepair()}
          onMeshDecimate={(ratio) => void runMeshDecimate(ratio)}
          imageReliefPreview={imageReliefPreview}
          onImageReliefPreview={(settings) => void previewImageRelief(settings)}
          onImageReliefApply={(settings, sha) => void applyImageRelief(settings, sha)}
          onCancelImageReliefPreview={cancelImageReliefPreview}
          savePath={savePath} setSavePath={setSavePath}
          openPath={openPath} setOpenPath={setOpenPath}
          exportPath={exportPath} setExportPath={setExportPath}
          onSave={() => void doSave()}
          onOpen={() => void doOpen()}
          onExport={(f) => void doExport(f)}
        />
        {aiOpen && (
          <AiPanel
            documentRevision={doc?.revision ?? 0}
            commands={commands}
            onClose={() => setAiOpen(false)}
            onApply={applyAiPlan}
            onOpenHelp={openHelpArticle}
          />
        )}
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
        computing={computing || geometryBusy}
        geometryBusy={geometryBusy}
        geometryCancelling={geometryCancelling}
        onCancelGeometry={() => void cancelGeometry()}
        message={statusMsg}
        selectedFace={selectedFace}
        faceArea={faceAreaValue}
      />
      <Tooltips mode={tooltipMode} commands={commands} onOpenArticle={openHelpArticle} />
    </div>
  );
}
