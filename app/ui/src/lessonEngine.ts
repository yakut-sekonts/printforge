import type { DocState, DocStats, Lesson, LessonCheck, Point3 } from "./types";

export type StepStatus = "pending" | "done" | "skipped";

interface LessonContext {
  savedPath?: string;
  checks?: { id: string; status: string }[];
  checksRevision?: number;
}

interface LessonCheckpoint {
  documentInstanceId: string | number;
  revision: number;
}

export interface LessonRun {
  lesson: Lesson;
  lessonIndex: number;
  totalLessons: number;
  stepIndex: number;
  statuses: StepStatus[];
  paused: boolean;
  context?: LessonContext;
  checkpoint?: LessonCheckpoint;
}

export interface LessonEvent {
  type: string;
  command_id?: string;
  state?: DocState;
  stats?: DocStats;
  op?: string;
  radius?: number;
  distance?: number;
  normal?: Point3;
  translate?: Point3;
  code?: string;
  mode?: string;
  format?: string;
  path?: string;
  degrees_of_freedom?: number;
  checks?: { id: string; status: string }[];
}

export interface StoredLessonProgress {
  schema_version: 1;
  lesson_id: string;
  content_version: number;
  statuses: StepStatus[];
  paused: boolean;
  context?: LessonContext;
  checkpoint?: LessonCheckpoint;
}

const closeNumber = (actual: unknown, expected: number, tolerance = 1e-6): boolean =>
  typeof actual === "number" && Number.isFinite(actual) && Math.abs(actual - expected) <= tolerance;

function vectorMatches(actual: number[] | undefined | null, expected: number[], tolerance = 1e-6): boolean {
  return actual?.length === expected.length && expected.every((value, index) => closeNumber(actual[index], value, tolerance));
}

function nextPending(statuses: StepStatus[]): number {
  const index = statuses.findIndex((status) => status === "pending");
  return index < 0 ? statuses.length : index;
}

function validCheckpoint(value: unknown): value is LessonCheckpoint {
  if (!value || typeof value !== "object") return false;
  const checkpoint = value as Partial<LessonCheckpoint>;
  return (typeof checkpoint.documentInstanceId === "string" || typeof checkpoint.documentInstanceId === "number")
    && Number.isInteger(checkpoint.revision) && checkpoint.revision! >= 0;
}

function readContext(value: unknown): LessonContext | undefined {
  if (!value || typeof value !== "object") return undefined;
  const context = value as LessonContext;
  return {
    savedPath: typeof context.savedPath === "string" ? context.savedPath : undefined,
    checksRevision: Number.isInteger(context.checksRevision) ? context.checksRevision : undefined,
    checks: Array.isArray(context.checks)
      ? context.checks.filter((result) => result && typeof result.id === "string" && typeof result.status === "string")
      : undefined,
  };
}

export const lessonKey = (id: string, version = 1): string => `pf-lesson-${id}-v${version}`;

export function lessonMastered(statuses: StepStatus[]): boolean {
  return statuses.length > 0 && statuses.every((status) => status === "done");
}

export function createLessonRun(lesson: Lesson, lessonIndex: number, totalLessons: number): LessonRun {
  return { lesson, lessonIndex, totalLessons, stepIndex: 0, statuses: lesson.steps.map(() => "pending"), paused: false };
}

export function readLessonProgress(lesson: Lesson, raw: string | null): StoredLessonProgress | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const stored = parsed as Partial<StoredLessonProgress>;
    if (stored.schema_version !== 1 || stored.lesson_id !== lesson.lesson_id
      || stored.content_version !== (lesson.content_version ?? 1)
      || !Array.isArray(stored.statuses) || stored.statuses.length !== lesson.steps.length
      || !stored.statuses.every((status) => status === "pending" || status === "done" || status === "skipped")
      || typeof stored.paused !== "boolean") return null;
    if (stored.checkpoint != null && !validCheckpoint(stored.checkpoint)) return null;
    return {
      schema_version: 1,
      lesson_id: lesson.lesson_id,
      content_version: lesson.content_version ?? 1,
      statuses: [...stored.statuses],
      paused: stored.paused,
      checkpoint: stored.checkpoint,
      context: readContext(stored.context),
    };
  } catch {
    return null;
  }
}

export function serializeLessonProgress(run: LessonRun, state?: DocState): string {
  const checkpoint = state?.slot === "tutorial" && state.document_instance_id != null
    ? { documentInstanceId: state.document_instance_id, revision: state.revision }
    : run.checkpoint;
  const stored: StoredLessonProgress = {
    schema_version: 1,
    lesson_id: run.lesson.lesson_id,
    content_version: run.lesson.content_version ?? 1,
    statuses: [...run.statuses],
    paused: run.paused,
    checkpoint,
    context: run.context,
  };
  return JSON.stringify(stored);
}

export function restoreLessonRun(lesson: Lesson, lessonIndex: number, totalLessons: number, raw: string | null, state: DocState): LessonRun | null {
  const stored = readLessonProgress(lesson, raw);
  if (!stored?.checkpoint || state.slot !== "tutorial"
    || stored.checkpoint.documentInstanceId !== state.document_instance_id
    || stored.checkpoint.revision !== state.revision) return null;
  return {
    lesson, lessonIndex, totalLessons, stepIndex: nextPending(stored.statuses), statuses: stored.statuses,
    paused: stored.paused, context: stored.context, checkpoint: stored.checkpoint,
  };
}

function matchesState(check: LessonCheck, event: LessonEvent): boolean {
  const state = event.state;
  if (check.template && state?.template !== check.template) return false;
  if (check.params && !Object.entries(check.params).every(([name, value]) => closeNumber(state?.params[name], value))) return false;
  const stats = check.preview ? event.stats : state?.stats;
  if (check.bbox_size) {
    const bounds = stats?.bbox;
    const size = bounds ? [bounds[3] - bounds[0], bounds[4] - bounds[1], bounds[5] - bounds[2]] : null;
    if (!vectorMatches(size, check.bbox_size, 0.001)) return false;
  }
  if (check.bbox && !vectorMatches(stats?.bbox, check.bbox, 0.001)) return false;
  if (check.volume != null && !closeNumber(stats?.volume, check.volume, Math.max(0.001, check.volume * 1e-6))) return false;
  if (check.solid_count != null && (!state && !check.preview || (stats?.solid_count ?? 0) !== check.solid_count)) return false;
  if (check.mesh_mode != null && stats?.mesh_mode !== check.mesh_mode) return false;
  if (check.boundary_edges != null && stats?.mesh_diagnostics?.boundary_edges !== check.boundary_edges) return false;
  if (check.hole_centers_abs_x != null && !stats?.hole_centers?.some(([coordinate]) => closeNumber(Math.abs(coordinate), check.hole_centers_abs_x!))) return false;
  return true;
}

export function lessonStepMatches(check: LessonCheck, event: LessonEvent, run: LessonRun): boolean {
  if (event.state?.slot === "main") return false;
  if (event.state?.error && check.type !== "error_shown") return false;
  if (check.normal && !vectorMatches(event.normal, check.normal)) return false;
  if (check.distance != null && !closeNumber(event.distance, check.distance)) return false;
  if (check.radius != null && !closeNumber(event.radius, check.radius)) return false;
  if (!matchesState(check, event)) return false;
  switch (check.type) {
    case "params": return event.type === "params" && !!event.state;
    case "command": return event.type === "command" && event.command_id === check.command_id;
    case "operation": return event.type === "operation" && !!event.state && event.op === check.op
      && (!check.nonzero_translate || !!event.translate?.some((value) => Number.isFinite(value) && Math.abs(value) > 1e-6));
    case "face_selected": return event.type === "face_selected";
    case "camera_rotated": return event.type === "camera_rotated";
    case "camera_zoomed": return event.type === "camera_zoomed";
    case "saved": return event.type === "saved" && !!(event.path ?? event.state?.path) && event.state?.dirty === false;
    case "reopened": return event.type === "reopened"
      && (!check.same_saved_path || !!run.context?.savedPath && (event.path ?? event.state?.path) === run.context.savedPath);
    case "exported": return event.type === "exported" && (!check.format || event.format === check.format)
      && (!check.formats || !!event.format && check.formats.includes(event.format));
    case "error_shown": return event.type === "error_shown" && (!check.code || event.code === check.code);
    case "check_result": return event.type === "check_result" && !!event.state
      && !!event.checks?.some((result) => result.id === check.id && result.status === check.status);
    case "inspection": {
      if (event.type !== "inspection" || !event.state) return false;
      if (!check.required_check) return true;
      if (run.context?.checksRevision !== event.state.revision) return false;
      const checks = event.checks ?? run.context.checks;
      return !!checks?.some((result) => result.id === check.required_check?.id && result.status === check.required_check.status);
    }
    case "mesh_source_applied": return event.type === "mesh_source_applied" && event.mode === "mesh" && !!event.state;
    case "mesh_inspected": return event.type === "mesh_inspected" && !!event.state;
    case "sketch_solved": return event.type === "sketch_solved" && !!event.state && event.degrees_of_freedom === check.degrees_of_freedom;
    case "image_preview": return event.type === "image_preview" && !!event.state && !!event.stats && (event.state.stats?.solid_count ?? 0) === 0;
    case "ai_applied": return event.type === "ai_applied" && !!event.state;
    default: return false;
  }
}

export function advanceLesson(run: LessonRun, event: LessonEvent): LessonRun {
  if (run.paused || run.stepIndex >= run.lesson.steps.length) return run;
  if (run.lesson.steps[run.stepIndex].check.type === "inspection" && event.type === "check_result"
    && event.state?.slot === "tutorial" && !event.state.error && event.checks) {
    return {
      ...run,
      context: { ...run.context, checks: event.checks, checksRevision: event.state.revision },
      checkpoint: event.state.document_instance_id != null
        ? { documentInstanceId: event.state.document_instance_id, revision: event.state.revision }
        : run.checkpoint,
    };
  }
  if (!lessonStepMatches(run.lesson.steps[run.stepIndex].check, event, run)) return run;
  const statuses = [...run.statuses];
  statuses[run.stepIndex] = "done";
  const context = { ...run.context };
  if (event.type === "saved") context.savedPath = event.path ?? event.state?.path ?? undefined;
  if (event.type === "check_result") {
    context.checks = event.checks;
    context.checksRevision = event.state?.revision;
  }
  return {
    ...run, statuses, context, stepIndex: nextPending(statuses),
    checkpoint: event.state?.document_instance_id != null
      ? { documentInstanceId: event.state.document_instance_id, revision: event.state.revision }
      : run.checkpoint,
  };
}

export function skipLessonStep(run: LessonRun): LessonRun {
  if (run.stepIndex >= run.statuses.length) return run;
  const statuses = [...run.statuses];
  statuses[run.stepIndex] = "skipped";
  return { ...run, statuses, stepIndex: nextPending(statuses) };
}
