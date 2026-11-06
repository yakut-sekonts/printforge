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
import { acceptsDocumentState, documentGeometryChanged, imageReliefSettingsKey, isEditableTarget } from "./documentState";
import { parameterValues } from "./parameterEditing";
import { sizeLabel } from "./bodyResizing";
import type { BodyResize, Size3 } from "./bodyResizing";
import { Viewport, faceArea, ViewName } from "./viewport";
import type { TransformAxis } from "./viewport";
import {
  analyzeFace, pushPullDelta, pushPullValue, resolveFaceEditTarget, resolveFaceFeatureTarget,
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
import { LessonBar } from "./LessonBar";
import { advanceLesson, createLessonRun, lessonKey, lessonMastered, readLessonProgress, restoreLessonRun, serializeLessonProgress, skipLessonStep } from "./lessonEngine";
import type { LessonEvent, LessonRun } from "./lessonEngine";
import { revealCommand } from "./revealCommand";
import { AiPanel } from "./AiPanel";
import { SelectionCoach } from "./SelectionCoach";
import { PrimitivePicker } from "./PrimitivePicker";
import { UnsavedChangesDialog } from "./UnsavedChangesDialog";
import { DesignerWorkbench, OperationHistory } from "./DesignerWorkbench";
import { InteractionTools } from "./InteractionTools";
import { RecoveryNotice } from "./RecoveryNotice";
import { PreviewQueue } from "./designer";
import type { DesignerAction } from "./designer";

const TOOLTIP_KEY = "pf-tooltip-mode";
const ACTIVE_LESSON_KEY = "pf-active-lesson";

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
  const [bodyResizeMode, setBodyResizeMode] = useState(false);
  const [bodyResizeSize, setBodyResizeSize] = useState<Size3 | null>(null);
  const [historyEdit, setHistoryEdit] = useState<number | null>(null);
  const [interactionActive, setInteractionActive] = useState(false);
  const [designerActive, setDesignerActive] = useState(false);
  const preserveResizeRef = useRef(true);
  const designerQueue = useRef(new PreviewQueue());
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
    faceIndex?: number; faceDiameter?: number; faceError?: string; distance?: number;
  } | null>(null);
  const [measureBusy, setMeasureBusy] = useState(false);
  const [performanceConfig, setPerformanceConfig] = useState<PerformanceConfig | null>(null);
  const [nativeE2eConfig, setNativeE2eConfig] = useState<NativeE2eConfig | null>(null);
  const [unsavedRequest, setUnsavedRequest] = useState<{ document: DocState; proceed?: () => Promise<void> } | null>(null);
  const [unsavedPath, setUnsavedPath] = useState("");
  const [unsavedBusy, setUnsavedBusy] = useState(false);
  const [unsavedError, setUnsavedError] = useState<string | null>(null);

  const viewportRef = useRef<Viewport | null>(null);
  const viewportEl = useRef<HTMLDivElement>(null);
  const meshToken = useRef(0);
  const printRequestToken = useRef(0);
  const measureRequestToken = useRef(0);
  const cancelPending = useRef(false);
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
  const bodyResizeCommitRef = useRef<(_resize: BodyResize) => void>(() => {});
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
          const analysis = meshRef.current ? analyzeFace(meshRef.current, face) : null;
          lessonEvent({ type: "face_selected", normal: analysis?.normal });
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
      onBodyResizePreview: (size) => setBodyResizeSize(size),
      onBodyResizeCommit: (resize) => bodyResizeCommitRef.current(resize),
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
    viewportRef.current?.setEditingEnabled(!computing && !geometryBusy && !meshLoading && !whatIsThis && !unsavedRequest);
  }, [computing, geometryBusy, meshLoading, whatIsThis, unsavedRequest]);

  useEffect(() => {
    document.body.classList.toggle("what-is-this", whatIsThis);
  }, [whatIsThis]);

  useEffect(() => {
    if (!isTauri()) return;
    let disposed = false;
    const subscriptions: Array<() => void> = [];
    void import("@tauri-apps/api/event").then(async ({ listen }) => {
      const requested = await listen<DocState>("printforge-close-requested", (event) => {
        setWhatIsThis(false);
        setUnsavedRequest({ document: event.payload });
        setUnsavedPath(event.payload.path ?? "");
        setUnsavedError(null);
      });
      const blocked = await listen<{ message: string }>("printforge-close-blocked", (event) => setStatusMsg(event.payload.message));
      if (disposed) { requested(); blocked(); }
      else subscriptions.push(requested, blocked);
    }).catch((error) => setStatusMsg(`Не удалось включить защиту закрытия: ${parseIpcError(error).message}`));
    return () => { disposed = true; subscriptions.forEach((unsubscribe) => unsubscribe()); };
  }, []);

  // ---------- работа с документом ----------
  const clearDesignerPreview = useCallback(() => {
    designerQueue.current.invalidate();
    viewportRef.current?.setOperationPreview(null);
  }, []);

  const designerPreview = useCallback((action: DesignerAction, done: (error: string | null) => void) => {
    const source = docRef.current;
    if (!source || documentActionPending.current) return () => {};
    let cancelled = false;
    designerQueue.current.schedule(async () => {
      const candidate = await backend.docDesignerPreview(action, source);
      return backend.docGetImportedMesh(candidate.mesh);
    }, (candidate) => {
      const active = docRef.current;
      if (cancelled || active?.revision !== source.revision || active.document_instance_id !== source.document_instance_id || active.slot !== source.slot) return;
      viewportRef.current?.setOperationPreview(candidate); done(null);
    }, (cause) => {
      if (cancelled) return;
      viewportRef.current?.setOperationPreview(null); done(parseIpcError(cause).message);
    });
    return () => { cancelled = true; clearDesignerPreview(); };
  }, [clearDesignerPreview]);

  const applyDoc = useCallback((state: DocState) => {
    const cur = docRef.current;
    // страж устаревших ответов: та же пара doc_id+slot, но меньшая ревизия
    if (!acceptsDocumentState(cur, state)) return;
    if (documentGeometryChanged(cur, state)) {
      designerQueue.current.invalidate();
      viewportRef.current?.setOperationPreview(null);
      viewportRef.current?.setDesignerTool(null);
      setHistoryEdit(null);
      printRequestToken.current += 1;
      measureRequestToken.current += 1;
      setPrintChecks(null);
      setMeasureResult(null);
      setImportedStats(null);
      setImportPreview(null);
      setImageReliefPreview(null);
      setConstraintSolution(null);
      if (!state.stats?.is_valid || state.stats.mesh_mode) setBodyResizeMode(false);
      viewportRef.current?.cancelTransformPreview();
      viewportRef.current?.cancelBodyResizePreview();
      viewportRef.current?.cancelPushPullPreview();
      viewportRef.current?.setFaceFeaturePreview(null);
      viewportRef.current?.setFaceDomePreview(null);
      viewportRef.current?.setSheetBendPreview(null);
      setMoveMode(false);
      setMovePreview(null);
      setSelectedFace(null);
      if (cur && (cur.document_instance_id !== state.document_instance_id || cur.doc_id !== state.doc_id || cur.slot !== state.slot)) {
        setBodyResizeMode(false);
        setSelectedPartId(null);
        setSelectedPartIds([]);
      }
      viewportRef.current?.setSelectedFace(null);
      setEdgeTool((current) => ({ ...current, active: false, selected: null, partId: null }));
      viewportRef.current?.setSplitPreview(null);
    }
    docRef.current = state;
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
      setComputing(false);
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
      designerQueue.current.invalidate();
      viewportRef.current?.setOperationPreview(null);
      await designerQueue.current.drain();
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
    if (!geometryBusy || cancelPending.current) return;
    cancelPending.current = true;
    setGeometryCancelling(true);
    try {
      const result = await backend.geometryCancel();
      setStatusMsg(result.cancelled
        ? "Останавливаем вычисление; подтверждённая модель сохранена"
        : "Активное вычисление уже завершилось");
    } catch (error) {
      setStatusMsg(`Не удалось отменить вычисление: ${parseIpcError(error).message}`);
    } finally {
      cancelPending.current = false;
      setGeometryCancelling(false);
    }
  }, [geometryBusy, geometryCancelling]);

  // ---------- уроки ----------
  const lessonEvent = useCallback((ev: LessonEvent) => {
    const run = lessonRef.current;
    if (!run || run.paused) return;
    const next = advanceLesson(run, { ...ev, state: ev.state ?? docRef.current ?? undefined });
    if (next !== run) {
      lessonRef.current = next;
      setLessonRun(next);
    }
  }, []);

  const commitDesignerAction = useCallback(async (action: DesignerAction) => {
    const source = docRef.current;
    if (!source) return false;
    const state = await runBackend(() => backend.docDesignerAction(action, source), true);
    if (!state || state.error) { if (state?.error) setStatusMsg(state.error.message); return false; }
    const operation = action.type === "append" ? action.operation : action.type === "edit" ? source.operations?.[action.index] : null;
    if (operation) lessonEvent({ type: "operation", op: String(operation.op), state,
      translate: "translate" in operation ? operation.translate as [number, number, number] : undefined });
    return true;
  }, [runBackend, lessonEvent]);

  useEffect(() => {
    if (!lessonRun || doc?.slot !== "tutorial") return;
    localStorage.setItem(lessonKey(lessonRun.lesson.lesson_id, lessonRun.lesson.content_version), serializeLessonProgress(lessonRun, doc));
    localStorage.setItem(ACTIVE_LESSON_KEY, lessonRun.lesson.lesson_id);
  }, [doc, lessonRun]);

  useEffect(() => {
    if (lessonRef.current || doc?.slot !== "tutorial" || !lessons.length) return;
    const lesson = lessons.find((candidate) => candidate.lesson_id === localStorage.getItem(ACTIVE_LESSON_KEY));
    if (!lesson) return;
    const restored = restoreLessonRun(lesson, lessons.indexOf(lesson), lessons.length,
      localStorage.getItem(lessonKey(lesson.lesson_id, lesson.content_version)), doc);
    if (restored) {
      lessonRef.current = restored;
      setLessonRun(restored);
    }
  }, [doc, lessons]);

  const undoDocument = useCallback(async () => {
    const state = await runBackend(() => backend.docUndo());
    if (!state) return;
    setStatusMsg("Последняя операция отменена");
    lessonEvent({ type: "command", command_id: "op.undo", state });
  }, [runBackend, lessonEvent]);

  const redoDocument = useCallback(async () => {
    const state = await runBackend(() => backend.docRedo());
    if (!state) return;
    setStatusMsg("Операция повторена");
    lessonEvent({ type: "command", command_id: "op.redo", state });
  }, [runBackend, lessonEvent]);

  useEffect(() => {
    const run = lessonRun;
    if (!run || run.stepIndex >= run.lesson.steps.length) return;
    const check = run.lesson.steps[run.stepIndex].check;
    if (check.type === "params" && doc) lessonEvent({ type: "params", state: doc });
    if (check.type === "error_shown" && doc?.error) lessonEvent({ type: "error_shown", code: doc.error.code });
  }, [doc, lessonRun, lessonEvent]);

  const startLesson = useCallback(async (lessonId: string, restart = false) => {
    const lesson = lessons.find((l) => l.lesson_id === lessonId);
    if (!lesson) return;
    if (documentActionPending.current || geometryOperationCount.current > 0) return;
    documentActionPending.current = true;
    lessonRef.current = null;
    setLessonRun(null);
    setComputing(true);
    try {
      const idx = lessons.indexOf(lesson);
      if (!restart) {
        const previous = await backend.docSwitchSlot("tutorial");
        const restored = restoreLessonRun(lesson, idx, lessons.length,
          localStorage.getItem(lessonKey(lesson.lesson_id, lesson.content_version)), previous);
        if (restored) {
          applyDoc(previous);
          lessonRef.current = restored;
          setLessonRun(restored);
          return;
        }
      }
      let state = await backend.docNewTutorial();
      applyDoc(state);
      if (lessonId === "navigation" || lessonId === "save-export") {
        state = await backend.docCreate("box", { length: 40, width: 30, height: 20 });
        applyDoc(state);
      }
      const run = createLessonRun(lesson, idx, lessons.length);
      lessonRef.current = run;
      setLessonRun(run);
      setSelectedFace(null);
    } catch (e) {
      setStatusMsg(`Не удалось начать урок: ${(e as GeoError).message ?? e}`);
    } finally {
      documentActionPending.current = false;
      setComputing(false);
    }
  }, [lessons, applyDoc]);

  const exitLesson = useCallback(async () => {
    if (documentActionPending.current || geometryOperationCount.current > 0) return;
    documentActionPending.current = true;
    setComputing(true);
    lessonRef.current = null;
    setLessonRun(null);
    setSelectedFace(null);
    try {
      const state = await backend.docSwitchSlot("main");
      applyDoc(state);
    } catch (error) {
      setStatusMsg(`Не удалось выйти из урока: ${(error as GeoError).message ?? error}`);
    } finally {
      documentActionPending.current = false;
      setComputing(false);
    }
  }, [applyDoc]);

  const lessonDone = useCallback((lessonId: string) => {
    const lesson = lessons.find((l) => l.lesson_id === lessonId);
    if (!lesson) return false;
    const progress = readLessonProgress(lesson, localStorage.getItem(lessonKey(lessonId, lesson.content_version)));
    return progress != null && lessonMastered(progress.statuses);
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
    const template = templates.find((candidate) => candidate.template_id === (part?.template ?? cur.template)) ?? null;
    try { num = evalExpression(raw, parameterValues(cur, template, part?.part_id)); }
    catch (e) { setStatusMsg(`Ошибка выражения: ${(e as Error).message}`); return; }
    const state = await runBackend(() => backend.docSetParameter(name, num, raw, partId), true);
    if (state) lessonEvent({ type: "params", state });
  }, [runBackend, lessonEvent, templates]);

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
      if (target.mode === "offset") lessonEvent({ type: "operation", op: "face_offset", distance: value, normal: target.normal, state });
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

    viewport?.setPushPullHandle(moveMode || bodyResizeMode ? null : target);
    setPushPull({
      target,
      value: target ? String(target.current) : "",
      dragging: false,
      reason,
    });
    setFaceFeatureTarget(featureTarget);
    setSheetBendTarget(bendTarget);
    setFaceFeatureReason(featureReason);
  }, [selectedFace, selectedPartId, mesh, doc, templates, importedStats, moveMode, bodyResizeMode]);

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
      viewport?.setBodyResizeHandle(null);
      return;
    }
    const selectedSolidIndices = solidIndicesForParts(liveParts, selectedPartId ? [selectedPartId] : []);
    viewport.setSelectedSolids(solidIndicesForParts(liveParts, selectedPartIds));
    viewport.setTransformHandle(moveMode && selectedPartId && selectedSolidIndices.length > 0
      ? { partId: selectedPartId, solidIndices: selectedSolidIndices }
      : null);
    viewport.setBodyResizeHandle(bodyResizeMode && selectedPartId && !doc?.stats?.mesh_mode && selectedSolidIndices.length > 0
      ? { partId: selectedPartId, solidIndices: selectedSolidIndices,
        bbox: liveParts.find((part) => part.part_id === selectedPartId)?.bbox }
      : null);
  }, [doc, mesh, selectedPartId, selectedPartIds, moveMode, bodyResizeMode]);

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
    const source = docRef.current;
    const state = await runBackend(() => source?.stats?.mesh_mode
      ? backend.docDesignerAction({ type: "append", operation: { op: "mesh_transform", translate } }, source)
      : backend.docTransform(id, translate), true);
    viewportRef.current?.cancelTransformPreview();
    setMovePreview(null);
    if (state && !state.error) {
      const [x, y, z] = translate;
      setStatusMsg(`Деталь перемещена: X ${x} мм, Y ${y} мм, Z ${z} мм`);
      lessonEvent({ type: "operation", op: "transform", translate, state });
    }
  }, [runBackend, activePartId, lessonEvent]);

  function startBodyResize() {
    const id = activePartId();
    if (docRef.current?.stats?.mesh_mode) {
      setStatusMsg("Форма мышью доступна для точных BRep-тел, но не для импортированной сетки.");
      return;
    }
    if (!id) return;
    cancelEdgeTool(); cancelPushPull();
    setMoveMode(false); setMovePreview(null);
    setSelectedFace(null);
    setSelectedPartId(id); setSelectedPartIds([id]);
    viewportRef.current?.setSplitPreview(null);
    viewportRef.current?.setTransformHandle(null);
    setBodyResizeMode(true);
    setStatusMsg("Потяните синий угол рамки или цветную ручку. Противоположный угол остаётся на месте.");
  }

  bodyResizeCommitRef.current = (resize) => {
    void (async () => {
      const source = docRef.current;
      if (!source) return;
      const preserve = preserveResizeRef.current && source.stats?.parts?.find((part) => part.part_id === resize.target_id)?.parametric_resize;
      const state = await runBackend(() => backend.docDesignerAction({ type: "append", operation: {
        op: preserve ? "resize_parametric" : "resize_body", ...resize,
      } }, source), true);
      viewportRef.current?.cancelBodyResizePreview();
      if (state && !state.error) {
        const bounds = state.stats?.parts?.find((part) => part.part_id === resize.target_id)?.bbox;
        const actualSize = bounds?.length === 6
          ? bounds.slice(3).map((value, axis) => value - bounds[axis]) as Size3 : resize.size;
        setStatusMsg(`Размер тела: ${sizeLabel(actualSize)}. Отменить — Cmd/Ctrl+Z.`);
        lessonEvent({ type: "operation", op: "resize_body", state });
      }
    })();
  };

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
    if (documentActionPending.current || geometryOperationCount.current > 0) return;
    setComputing(true);
    beginGeometryOperation();
    try {
      const solution = await backend.sketchSolve(sketch);
      setConstraintSolution(solution);
      setStatusMsg(solution.degrees_of_freedom === 0
        ? "Эскиз полностью определён"
        : `Эскиз недоопределён: ${solution.degrees_of_freedom} DOF`);
      lessonEvent({ type: "sketch_solved", degrees_of_freedom: solution.degrees_of_freedom });
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
    if (documentActionPending.current || geometryOperationCount.current > 0) return;
    const token = ++measureRequestToken.current;
    setMeasureResult(null);
    setMeasureBusy(true);
    beginGeometryOperation();
    try {
      const bboxRes = await backend.measure({ type: "bbox" });
      const volRes = await backend.measure({ type: "volume" });
      if (token !== measureRequestToken.current) return;
      setMeasureResult((prev) => ({
        ...prev,
        source: (bboxRes.source as string) ?? "brep",
        bbox: (bboxRes.bbox as number[]) ?? (bboxRes.min && bboxRes.max ? [...(bboxRes.min as number[]), ...(bboxRes.max as number[])] as number[] : undefined),
        volume: volRes.volume as number | undefined,
        faceError: undefined,
      }));
    } catch (e) {
      if (token !== measureRequestToken.current) return;
      setStatusMsg(`Ошибка измерения: ${parseIpcError(e).message}`);
    } finally {
      endGeometryOperation();
      setMeasureBusy(false);
    }
  }, [beginGeometryOperation, endGeometryOperation]);

  const runMeasureFace = useCallback(async () => {
    if (selectedFace == null) return;
    if (documentActionPending.current || geometryOperationCount.current > 0) return;
    const token = ++measureRequestToken.current;
    setMeasureResult(null);
    setMeasureBusy(true);
    beginGeometryOperation();
    try {
      const res = await backend.measure({ type: "face_diameter", face_index: selectedFace });
      if (token !== measureRequestToken.current) return;
      setMeasureResult((prev) => ({ ...prev, faceIndex: selectedFace, faceDiameter: res.diameter as number | undefined, faceError: undefined }));
    } catch (e) {
      if (token !== measureRequestToken.current) return;
      const err = parseIpcError(e);
      setMeasureResult((prev) => ({ ...prev, faceIndex: selectedFace, faceDiameter: undefined, faceError: err.message }));
    } finally {
      endGeometryOperation();
      setMeasureBusy(false);
    }
  }, [selectedFace, beginGeometryOperation, endGeometryOperation]);

  const runMeasureDistance = useCallback(async (p0: [number, number, number], p1: [number, number, number]) => {
    if (documentActionPending.current || geometryOperationCount.current > 0) return;
    const token = ++measureRequestToken.current;
    setMeasureResult(null);
    if (![...p0, ...p1].every(Number.isFinite)) {
      setStatusMsg("Координаты должны быть конечными числами");
      return;
    }
    setMeasureBusy(true);
    beginGeometryOperation();
    try {
      const res = await backend.measure({ type: "distance", p0, p1 });
      if (token !== measureRequestToken.current) return;
      setMeasureResult((prev) => ({ ...prev, distance: res.distance as number | undefined }));
    } catch (e) {
      if (token !== measureRequestToken.current) return;
      setStatusMsg(`Ошибка измерения: ${parseIpcError(e).message}`);
    } finally {
      endGeometryOperation();
      setMeasureBusy(false);
    }
  }, [beginGeometryOperation, endGeometryOperation]);

  // ---------- обработка рёбер ----------
  const startEdgeTool = useCallback((kind: EdgeFeatureKind) => {
    viewportRef.current?.setBodyResizeHandle(null);
    setBodyResizeMode(false);
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
    } else if (state?.error) {
      lessonEvent({ type: "error_shown", code: state.error.code, radius: size, state });
    }
  }, [runBackend, cancelEdgeTool, lessonEvent, activePartId]);

  const clearErrorOrUndo = useCallback(() => {
    void runBackend(() => backend.docClearError());
  }, [runBackend]);

  // ---------- проверка печати ----------
  useEffect(() => { if (!printChecks) viewportRef.current?.setPrintDiagnostics(null); }, [printChecks]);

  const runPrintCheck = useCallback(async (printer: { x: number; y: number; z: number; minimum_wall?: number }) => {
    if (documentActionPending.current || geometryOperationCount.current > 0) return;
    const token = ++printRequestToken.current;
    setPrintChecks(null);
    if (!Object.values(printer).every((value) => Number.isFinite(value) && value > 0)) {
      setStatusMsg("Габариты принтера должны быть положительными конечными числами");
      return;
    }
    setPrintBusy(true);
    beginGeometryOperation();
    try {
      const res = await backend.printCheck(printer);
      if (token !== printRequestToken.current) return;
      setPrintChecks(res.checks ?? []);
      viewportRef.current?.setPrintDiagnostics({ x: printer.x, y: printer.y, z: printer.z }, (res.checks ?? []).flatMap((check) => check.issues?.map((issue) => issue.point) ?? []));
      lessonEvent({ type: "check_result", checks: res.checks ?? [], state: docRef.current ?? undefined });
    } catch (e) {
      setStatusMsg(`Ошибка проверки: ${parseIpcError(e).message}`);
    } finally {
      endGeometryOperation();
      setPrintBusy(false);
    }
  }, [beginGeometryOperation, endGeometryOperation]);

  // ---------- импорт ----------
  const runImport = useCallback(async (path: string, format: "step" | "stl", unitScale?: number, confirmed = false): Promise<void> => {
    if (documentActionPending.current || geometryOperationCount.current > 0) return;
    const current = docRef.current;
    if (format === "step" && current?.dirty && !confirmed) {
      setUnsavedRequest({ document: current, proceed: () => runImport(path, format, unitScale, true) });
      setUnsavedPath(current.path ?? "");
      setUnsavedError(null);
      return;
    }
    setImportBusy(true);
    beginGeometryOperation();
    try {
      const res = await backend.docImport(expandTilde(path), format, unitScale);
      if (format === "stl" && unitScale === undefined) {
        // первый проход: показываем габарит и спрашиваем единицы
        setImportPreview(res);
      } else if (res.document) {
        applyDoc(res.document);
        setStatusMsg(`Открыта модель STEP: ${expandTilde(path)}. Сохраните её как новый проект.`);
        lessonEvent({ type: "imported", mode: res.mode, state: res.document });
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
  }, [applyDoc, beginGeometryOperation, endGeometryOperation]);

  const applyMeshImport = useCallback(async (path: string, unitScale: number) => {
    const state = await runBackend(() => backend.docMeshImportApply(expandTilde(path), "stl", unitScale), true);
    if (state && !state.error) {
      setImportPreview(null);
      setStatusMsg(`Mesh применён к документу: ${expandTilde(path)}`);
      lessonEvent({ type: "mesh_source_applied", mode: "mesh", state });
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
    if (documentActionPending.current || geometryOperationCount.current > 0) return;
    setImageReliefPreview(null);
    setComputing(true);
    beginGeometryOperation();
    try {
      const preview = await backend.imageReliefPreview({
        ...settings, path: expandTilde(settings.path),
      });
      const previewMesh = await backend.docGetImportedMesh(preview.mesh);
      setMesh(previewMesh);
      setImportedStats(preview.stats);
      setImageReliefPreview({ ...preview, settings_key: imageReliefSettingsKey(settings) });
      setStatusMsg("Decorative mesh preview готов; документ не изменён");
      lessonEvent({ type: "image_preview", stats: preview.stats });
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
    if (!imageReliefPreview || imageReliefPreview.settings_key !== imageReliefSettingsKey(settings) ||
        imageReliefPreview.source_sha256 !== expectedSha256) {
      setStatusMsg("Настройки изменились. Обновите Preview перед применением.");
      return;
    }
    const state = await runBackend(() => backend.docImageReliefApply({
      ...settings, path: expandTilde(settings.path),
    }, expectedSha256, imageReliefPreview.settings_sha256), true);
    if (state && !state.error) {
      setImageReliefPreview(null);
      setStatusMsg("Decorative mesh применён одной транзакцией");
      lessonEvent({ type: "operation", op: "image_relief_source" });
    }
  }, [imageReliefPreview, runBackend, lessonEvent]);

  const cancelImageReliefPreview = useCallback(() => {
    setImageReliefPreview(null);
    setImportedStats(null);
    const current = docRef.current;
    if (current?.stats) applyDoc(current);
    else setMesh(null);
    setStatusMsg("Decorative mesh preview отменён; документ не изменён");
  }, [applyDoc]);

  // ---------- файлы ----------
  const doSave = useCallback(async (saveAs = false) => {
    const source = docRef.current;
    if (!source || documentActionPending.current || geometryOperationCount.current > 0) return;
    let target = saveAs ? expandTilde(savePath) : source.path ?? expandTilde(savePath);
    if (isTauri() && (saveAs || !source.path)) {
      setComputing(true);
      try {
        const chosen = await backend.dialogSavePath(target.split(/[\\/]/).pop() || "Без названия.printforge");
        if (!chosen) { setStatusMsg("Сохранение отменено"); return; }
        const active = docRef.current;
        if (!active || active.document_instance_id !== source.document_instance_id || active.revision !== source.revision || active.slot !== source.slot) {
          setStatusMsg("Документ изменился во время выбора пути. Повторите сохранение."); return;
        }
        target = chosen;
      } catch (cause) { setStatusMsg(`Ошибка выбора файла: ${parseIpcError(cause).message}`); return; }
      finally { setComputing(false); }
    }
    const state = await runBackend(() => backend.docSave(target));
    if (state) {
      setSavePath(state.path ?? target);
      setStatusMsg(`Сохранено: ${state.path ?? target}`);
      lessonEvent({ type: "saved", state, path: state.path ?? undefined });
    }
  }, [savePath, runBackend, lessonEvent]);

  const continueUnsavedAction = async (save: boolean) => {
    const request = unsavedRequest;
    if (!request || unsavedBusy) return;
    setUnsavedBusy(true);
    setUnsavedError(null);
    try {
      let snapshot = request.document;
      if (save) {
        snapshot = request.proceed
          ? await backend.docSave(expandTilde(unsavedPath.trim()))
          : await backend.docSaveMain(expandTilde(unsavedPath.trim()));
        if (snapshot.slot === docRef.current?.slot) applyDoc(snapshot);
      }
      if (request.proceed) {
        const current = docRef.current;
        if (!current || current.document_instance_id !== snapshot.document_instance_id || current.revision !== snapshot.revision) {
          throw new Error("Документ изменился. Отмените действие и повторите импорт.");
        }
        setUnsavedRequest(null);
        await request.proceed();
      } else {
        await backend.docConfirmClose(snapshot.document_instance_id!, snapshot.revision, !save);
      }
    } catch (error) {
      setUnsavedError(parseIpcError(error).message);
    } finally {
      setUnsavedBusy(false);
    }
  };

  const doOpen = useCallback(async () => {
    const state = await runBackend(() => backend.docOpen(expandTilde(openPath)));
    if (state) {
      setStatusMsg(`Открыто: ${state.path ?? expandTilde(openPath)}`);
      lessonEvent({ type: "reopened", state });
    }
  }, [openPath, runBackend, lessonEvent]);

  const doExport = useCallback(async (format: "stl" | "step" | "3mf") => {
    if (documentActionPending.current || geometryOperationCount.current > 0) return;
    const path = expandTilde(exportPath).replace(/\.(stl|step|stp|3mf)$/i, "") + "." + format;
    setComputing(true);
    beginGeometryOperation();
    try {
      const res = await backend.docExport(path, format);
      const kb = (res.bytes / 1024).toFixed(1);
      const volume = res.stats.volume;
      const volumeText = volume == null ? "объём неизвестен" : `объём ${Math.round(volume * 10) / 10} мм³`;
      setStatusMsg(`Экспортировано: ${res.path} — ${kb} КБ, ${volumeText}`);
      lessonEvent({ type: "exported", format, path: res.path });
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
    lessonEvent({ type: "ai_applied", state });
    setStatusMsg("AI-план применён одной транзакцией");
    return state.revision;
  }, [runBackend, lessonEvent]);

  const highlightCommand = useCallback((commandId: string) => {
    const result = revealCommand(commandId);
    if (result.status === "shown") {
      setHelpOpen(false);
      setStatusMsg(result.message);
    }
    return result;
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
      case "op.resize_body": startBodyResize(); break;
      case "op.face_offset":
        viewportRef.current?.setBodyResizeHandle(null);
        setBodyResizeMode(false);
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
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      if (el?.dataset.cmd === "app.help.what_is_this") {
        setWhatIsThis(false);
        return;
      }
      if (!el) {
        setStatusMsg("Для этой области нет отдельной статьи. Модель не изменена; выберите кнопку со справкой.");
        return;
      }
      const cmd = commands.find((c) => c.command_id === el.dataset.cmd);
      setWhatIsThis(false);
      if (cmd) openHelpArticle(cmd.help_id);
      else {
        const t = templates.find((x) => x.command_id === el.dataset.cmd);
        if (t) openHelpArticle(t.help_id);
        else setHelpOpen(true);
      }
    };
    const blockPointer = (event: PointerEvent) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!(event.target as HTMLElement).closest?.("[data-cmd]")) {
        setStatusMsg("Режим «Что это?»: действие заблокировано, модель не изменена. Escape — выйти.");
      }
    };
    const blockKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" && event.key !== "Tab") {
        event.preventDefault();
        event.stopImmediatePropagation();
        setStatusMsg("Режим «Что это?» не выполняет команды. Escape — выйти.");
      }
    };
    document.addEventListener("click", handler, true);
    document.addEventListener("pointerdown", blockPointer, true);
    document.addEventListener("keydown", blockKey, true);
    return () => {
      document.removeEventListener("click", handler, true);
      document.removeEventListener("pointerdown", blockPointer, true);
      document.removeEventListener("keydown", blockKey, true);
    };
  }, [whatIsThis, commands, templates, openHelpArticle]);

  // ---------- клавиатура ----------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (unsavedRequest) return;
      if (!whatIsThis && !isEditableTarget(e.target) && viewportRef.current?.handleModelingKey(e)) { e.preventDefault(); return; }
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") {
        if (isEditableTarget(e.target)) return;
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
        if (whatIsThis) { setWhatIsThis(false); return; }
        setHistoryEdit(null);
        clearDesignerPreview();
        if (bodyResizeMode) {
          viewportRef.current?.setBodyResizeHandle(null);
          setBodyResizeMode(false);
          return;
        }
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
        else {
          setSelectedFace(null);
          setSelectedPartId(null);
          setSelectedPartIds([]);
          viewportRef.current?.setSelectedFace(null);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [whatIsThis, helpOpen, aiOpen, moveMode, bodyResizeMode, unsavedRequest, undoDocument, redoDocument, doSave, doOpen, cancelEdgeTool, cancelPushPull, clearDesignerPreview]);

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
      <div className="workspace-shell" ref={(element) => { if (element) element.inert = unsavedRequest != null; }}>
      <TopBar commands={commands} doc={doc} docName={docName} onCommand={runCommand} />
      <div className="app-main">
        <LeftPanel
          doc={doc}
          templates={templates}
          importedStats={importedStats}
          selectedPartId={selectedPartId}
          selectedPartIds={selectedPartIds}
          history={<OperationHistory doc={doc} onEdit={setHistoryEdit} onSelect={(id) => {
            setSelectedPartId(id); setSelectedPartIds([id]); setSelectedFace(null);
          }} />}
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
          <RecoveryNotice busy={computing || geometryBusy || meshLoading || !!doc?.dirty || doc?.slot === "tutorial"} restore={async (name) => {
            const state = await runBackend(() => backend.recoveryRestore(name));
            return !!state && !state.error;
          }} />
          {doc && mesh && <InteractionTools doc={doc} mesh={mesh} viewport={viewportRef.current} selectedFace={selectedFace} selectedPartId={selectedPartId}
            busy={computing || geometryBusy || meshLoading || !!unsavedRequest} inspectMode={whatIsThis}
            active={interactionActive} onFinish={() => setInteractionActive(false)} suspended={designerActive}
            onClearSelection={() => { setSelectedFace(null); setSelectedPartId(null); setSelectedPartIds([]); }}
            onHistoryPick={(index) => { setInteractionActive(false); setHistoryEdit(index); }}
            preview={designerPreview} clearPreview={clearDesignerPreview} prepare={() => {
              setHistoryEdit(null); cancelEdgeTool(); cancelPushPull(); setBodyResizeMode(false); setMoveMode(false); setInteractionActive(true);
            }} commit={commitDesignerAction} />}
          {doc && mesh && <DesignerWorkbench key={`${doc.document_instance_id}:${doc.slot}:${doc.revision}:${selectedPartId}`}
            doc={doc} mesh={mesh} viewport={viewportRef.current} partId={selectedPartId} face={faceFeatureTarget}
            selectedRange={mesh.face_ranges.find((range) => range.face_index === selectedFace)} externalToolActive={interactionActive} onActiveChange={setDesignerActive}
            edge={edgeTool} busy={computing || geometryBusy || meshLoading || !!unsavedRequest} inspectMode={whatIsThis}
            sceneToolActive={bodyResizeMode || moveMode || edgeTool.active}
            historyIndex={historyEdit} onHistoryClose={() => setHistoryEdit(null)}
            onHistoryPick={setHistoryEdit} onPartSelect={(id) => { setSelectedPartId(id); setSelectedPartIds([id]); setSelectedFace(null); }}
            preview={designerPreview} clearPreview={clearDesignerPreview}
            commit={commitDesignerAction}
            prepare={() => {
              setInteractionActive(false);
              viewportRef.current?.setBodyResizeHandle(null); viewportRef.current?.setTransformHandle(null);
              viewportRef.current?.cancelPushPullPreview(); viewportRef.current?.setPushPullHandle(null);
              setBodyResizeMode(false); setMoveMode(false); cancelEdgeTool();
            }}
            onResizePolicy={(preserve) => { preserveResizeRef.current = preserve; }}
            onEdgeSize={(size) => setEdgeTool((current) => ({ ...current, size }))}
            onEdgeKind={startEdgeTool} onEdgeCancel={cancelEdgeTool}
            onStartResize={startBodyResize} onStartMove={() => {
              const id = activePartId();
              if (!id) return;
              cancelEdgeTool(); setBodyResizeMode(false); setSelectedPartId(id); setSelectedPartIds([id]); setMoveMode(true);
            }}
            onFaceActions={showFaceActions}
          />}
          <div className="view-toolbar" role="toolbar" aria-label="Виды">
            {hasBody && !doc?.stats?.mesh_mode && <button className={`btn ${bodyResizeMode ? "btn-primary" : ""}`}
              data-cmd="op.resize_body" disabled={computing || geometryBusy || meshLoading} aria-pressed={bodyResizeMode} onClick={() => {
                if (bodyResizeMode) { viewportRef.current?.setBodyResizeHandle(null); setBodyResizeMode(false); }
                else startBodyResize();
              }}>Форма мышью</button>}
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
          <div className={`scene-dock${bodyResizeMode ? " scene-dock-resize" : ""}`}>
          {!doc?.stats?.mesh_mode && !designerActive && !interactionActive && <SelectionCoach
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
            bodyResizeMode={bodyResizeMode}
            bodyResizeSize={bodyResizeSize}
            onStartBodyResize={startBodyResize}
            canResizeBody={!doc?.stats?.mesh_mode}
            onCancelBodyResize={() => {
              viewportRef.current?.setBodyResizeHandle(null);
              setBodyResizeMode(false);
            }}
            movePreview={movePreview}
            parts={sceneParts}
            splitDefaults={splitDefaults}
            onStartEdgeTool={startEdgeTool}
            onStartMove={() => {
              viewportRef.current?.setBodyResizeHandle(null);
              setBodyResizeMode(false);
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
          />}
          {lessonRun && (
            <LessonBar
              run={lessonRun}
              onSkip={() => {
                const next = skipLessonStep(lessonRun);
                lessonRef.current = next;
                setLessonRun(next);
              }}
              onTogglePause={() => setLessonRun({ ...lessonRun, paused: !lessonRun.paused })}
              onExit={() => void exitLesson()}
              onRestart={() => void startLesson(lessonRun.lesson.lesson_id, true)}
              onInspect={() => lessonEvent({ type: lessonRun.lesson.steps[lessonRun.stepIndex].check.type, state: docRef.current ?? undefined, checks: printChecks ?? undefined })}
            />
          )}
          </div>
        </main>
        <ParamsPanel
          doc={doc}
          busy={computing || geometryBusy || meshLoading}
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
          onInvalidateMeasurements={() => { measureRequestToken.current += 1; setMeasureResult(null); }}
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
          onInvalidatePrintChecks={() => { printRequestToken.current += 1; setPrintChecks(null); }}
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
          onSave={() => void doSave(true)}
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
      {unsavedRequest && <UnsavedChangesDialog replacing={!!unsavedRequest.proceed} path={unsavedPath} busy={unsavedBusy}
        error={unsavedError} onPath={setUnsavedPath} onSave={() => void continueUnsavedAction(true)}
        onDiscard={() => void continueUnsavedAction(false)} onCancel={() => { setUnsavedRequest(null); setUnsavedError(null); }} />}
    </div>
  );
}
