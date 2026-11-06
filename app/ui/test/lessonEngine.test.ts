import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  advanceLesson, createLessonRun, lessonMastered, readLessonProgress,
  restoreLessonRun, serializeLessonProgress, skipLessonStep,
} from "../src/lessonEngine.ts";
import type { LessonEvent, LessonRun } from "../src/lessonEngine.ts";
import type { DocState, DocStats, Lesson, Point3 } from "../src/types.ts";

const lessons = (JSON.parse(readFileSync(new URL("../../shared/lessons.json", import.meta.url), "utf8")) as { lessons: Lesson[] }).lessons;

function runFor(id: string): LessonRun {
  const index = lessons.findIndex((lesson) => lesson.lesson_id === id);
  assert.notEqual(index, -1);
  return createLessonRun(lessons[index], index, lessons.length);
}

function stats(size: Point3, volume: number, solidCount = 1): DocStats {
  return {
    bbox: [-size[0] / 2, -size[1] / 2, 0, size[0] / 2, size[1] / 2, size[2]],
    volume, solid_count: solidCount, face_count: 6, is_valid: true,
  };
}

function documentState(template: string | null = null, params: Record<string, number> = {}, geometry: DocStats | null = null, revision = 1): DocState {
  return {
    document_instance_id: "tutorial-1", revision, dirty: true, path: null, slot: "tutorial",
    template, params, expressions: {}, stats: geometry, error: null, can_undo: revision > 1, can_redo: false,
  };
}

function meshState(boundaryEdges: number, size: Point3 = [40, 30, 20], revision = 1): DocState {
  return documentState(null, {}, {
    ...stats(size, 24000), mesh_mode: true,
    mesh_diagnostics: {
      watertight: boundaryEdges === 0, winding_consistent: true, boundary_edges: boundaryEdges,
      non_manifold_edges: 0, degenerate_triangles: 0, components: 1, euler_number: 2,
      self_intersection: "unknown", self_intersection_detail: "not checked",
    },
  }, revision);
}

function complete(run: LessonRun, events: LessonEvent[]): LessonRun {
  for (const event of events) {
    const previous = run.stepIndex;
    run = advanceLesson(run, event);
    assert.equal(run.stepIndex, previous + 1, `${run.lesson.lesson_id}: ${event.type} did not complete exactly one step`);
  }
  assert.equal(run.stepIndex, run.lesson.steps.length);
  assert.equal(lessonMastered(run.statuses), true);
  return run;
}

const box20 = () => documentState("box", { length: 40, width: 30, height: 20 }, stats([40, 30, 20], 24000));
const box25 = () => documentState("box", { length: 40, width: 30, height: 20 }, stats([40, 30, 25], 30000), 2);

test("все 13 поставляемых уроков проходят только свои реальные последовательности событий", () => {
  assert.equal(lessons.length, 13);
  complete(runFor("navigation"), [
    { type: "camera_rotated" }, { type: "camera_zoomed" },
    { type: "command", command_id: "view.fit" }, { type: "command", command_id: "view.top" },
    { type: "face_selected", normal: [0, 0, 1] },
  ]);
  const moved = box25();
  moved.stats = { ...moved.stats!, bbox: [-10, -15, 0, 30, 15, 25] };
  complete(runFor("first-part"), [
    { type: "params", state: box20() }, { type: "face_selected", normal: [0, 0, 1] },
    { type: "operation", op: "face_offset", distance: 5, normal: [0, 0, 1], state: box25() },
    { type: "operation", op: "transform", translate: [10, 0, 0], state: moved },
    { type: "command", command_id: "op.undo", state: box25() },
  ]);
  const saved = { ...box20(), dirty: false, path: "/tmp/lesson.printforge" };
  complete(runFor("save-export"), [
    { type: "params", state: box20() }, { type: "saved", state: saved },
    { type: "operation", op: "face_offset", distance: 5, normal: [0, 0, 1], state: box25() },
    { type: "reopened", state: saved }, { type: "exported", format: "stl", state: saved },
  ]);
  complete(runFor("washer"), [
    { type: "params", state: documentState("washer", { outer_diameter: 20, inner_diameter: 6, height: 4 }, stats([20, 20, 4], 364 * Math.PI)) },
    { type: "params", state: documentState("washer", { outer_diameter: 24, inner_diameter: 6, height: 4 }, stats([24, 24, 4], 540 * Math.PI)) },
  ]);
  const case100 = documentState("case_with_lid", { length: 100, width: 60, height: 30, wall: 2, bottom: 2, gap: 0.2 }, stats([100, 60, 32], 43827.2, 2));
  const case120 = documentState("case_with_lid", { ...case100.params, length: 120 }, stats([120, 60, 32], 51187.2, 2), 2);
  complete(runFor("case-lid"), [
    { type: "params", state: case100 }, { type: "inspection", state: case100 }, { type: "params", state: case120 },
  ]);
  const bracket = documentState("bracket_l", {}, stats([40, 30, 30], 11000));
  const rounded = { ...bracket, revision: 2, stats: stats([40, 30, 30], 10974.2477796077) };
  complete(runFor("fillet-fix"), [
    { type: "params", state: bracket }, { type: "operation", op: "fillet", radius: 2, state: rounded },
    { type: "error_shown", code: "fillet_failed", radius: 50, state: rounded },
    { type: "operation", op: "fillet", radius: 2, state: { ...rounded, revision: 3 } },
  ]);
  complete(runFor("import"), [
    { type: "mesh_source_applied", mode: "mesh", state: meshState(0) },
    { type: "mesh_inspected", state: meshState(0) },
  ]);
  const print230 = documentState("plate", { length: 230 }, stats([230, 60, 4], 55200));
  const print200 = documentState("plate", { length: 200 }, stats([200, 60, 4], 48000), 2);
  complete(runFor("print-check"), [
    { type: "check_result", state: print230, checks: [{ id: "bed_fit", status: "fail" }, { id: "wall_thickness", status: "unknown" }] },
    { type: "check_result", state: print200, checks: [{ id: "bed_fit", status: "pass" }, { id: "wall_thickness", status: "unknown" }] },
    { type: "inspection", state: print200 },
  ]);
  const washer = documentState("washer", { outer_diameter: 20, inner_diameter: 6, height: 4 }, stats([20, 20, 4], 364 * Math.PI));
  complete(runFor("ai-assistant"), [
    { type: "ai_applied", state: washer }, { type: "command", command_id: "op.undo", state: documentState() },
  ]);
  const sketch = documentState(null, {}, stats([40, 20, 5], 3607.300918301276));
  complete(runFor("advanced-bodies"), [
    { type: "operation", op: "sketch_extrude", state: sketch },
    { type: "operation", op: "shell", state: documentState(null, {}, stats([40, 20, 20], 5000, 2), 2) },
    { type: "command", command_id: "op.undo", state: sketch },
  ]);
  complete(runFor("constraint-solver"), [
    { type: "sketch_solved", degrees_of_freedom: 0, state: documentState() },
    { type: "operation", op: "constrained_sketch_extrude", state: documentState(null, {}, stats([40, 20, 5], 4000)) },
    { type: "command", command_id: "op.undo", state: documentState() },
  ]);
  complete(runFor("mesh-repair"), [
    { type: "mesh_source_applied", mode: "mesh", state: meshState(4) },
    { type: "operation", op: "mesh_repair", state: meshState(0, [40, 30, 20], 2) },
    { type: "command", command_id: "op.undo", state: meshState(4, [40, 30, 20], 3) },
  ]);
  complete(runFor("image-relief"), [
    { type: "image_preview", state: documentState(), stats: stats([40, 20, 6], 3200) },
    { type: "operation", op: "image_relief_source", state: meshState(0, [40, 20, 6]) },
    { type: "exported", format: "3mf" },
  ]);
});

test("смещение другой грани на 1 мм, нулевой transform и ложный Undo не выполняют first-part", () => {
  let run = advanceLesson(runFor("first-part"), { type: "params", state: box20() });
  assert.equal(advanceLesson(run, { type: "face_selected", normal: [1, 0, 0] }), run);
  run = advanceLesson(run, { type: "face_selected", normal: [0, 0, 1] });
  assert.equal(advanceLesson(run, { type: "operation", op: "face_offset", distance: 1, normal: [1, 0, 0], state: box20() }), run);
  assert.equal(advanceLesson(run, { type: "operation", op: "face_offset", distance: 5, normal: [0, 0, 1], state: box20() }), run);
  run = advanceLesson(run, { type: "operation", op: "face_offset", distance: 5, normal: [0, 0, 1], state: box25() });
  assert.equal(advanceLesson(run, { type: "operation", op: "transform", translate: [0, 0, 0], state: box25() }), run);
  assert.equal(advanceLesson(run, { type: "operation", op: "transform", translate: [5, 0, 0] }), run);
  run = advanceLesson(run, { type: "operation", op: "transform", translate: [5, 0, 0], state: box25() });
  assert.equal(advanceLesson(run, { type: "command", command_id: "op.undo", state: box20() }), run);
});

test("один импорт не засчитывает отдельное наблюдение, диагностика проверяется по состоянию", () => {
  const initial = runFor("import");
  assert.equal(advanceLesson(initial, { type: "mesh_source_applied", mode: "mesh", state: meshState(4) }), initial);
  const imported = advanceLesson(initial, { type: "mesh_source_applied", mode: "mesh", state: meshState(0) });
  assert.deepEqual(imported.statuses, ["done", "pending"]);
  assert.equal(advanceLesson(imported, { type: "mesh_source_applied", mode: "mesh", state: meshState(0) }), imported);
  assert.equal(advanceLesson(imported, { type: "mesh_inspected", state: box20() }), imported);
  assert.equal(advanceLesson(imported, { type: "mesh_inspected", state: meshState(4) }), imported);
  assert.equal(advanceLesson(imported, { type: "mesh_inspected", state: meshState(0) }).stepIndex, 2);
});

test("reopen требует тот же файл и 20 мм, STEP не выдаётся за STL", () => {
  const saved = { ...box20(), dirty: false, path: "/tmp/lesson.printforge" };
  let run = advanceLesson(runFor("save-export"), { type: "params", state: box20() });
  assert.equal(advanceLesson(run, { type: "saved", state: { ...saved, dirty: true } }), run);
  run = advanceLesson(run, { type: "saved", state: saved });
  run = advanceLesson(run, { type: "operation", op: "face_offset", distance: 5, normal: [0, 0, 1], state: box25() });
  assert.equal(advanceLesson(run, { type: "reopened", state: { ...saved, path: "/tmp/other.printforge" } }), run);
  assert.equal(advanceLesson(run, { type: "reopened", state: { ...box25(), path: saved.path } }), run);
  run = advanceLesson(run, { type: "reopened", state: saved });
  assert.equal(advanceLesson(run, { type: "exported", format: "step" }), run);
  assert.equal(advanceLesson(run, { type: "exported" }), run);
  assert.equal(advanceLesson(run, { type: "exported", format: "stl" }).stepIndex, 5);
});

test("свежесть печатной проверки и статус unknown обязательны для шага наблюдения", () => {
  const state = documentState("plate", { length: 230 }, stats([230, 60, 4], 55200));
  let run = advanceLesson(runFor("print-check"), { type: "check_result", state, checks: [{ id: "bed_fit", status: "fail" }] });
  const smaller = { ...state, revision: 2, params: { length: 200 } };
  run = advanceLesson(run, { type: "check_result", state: smaller, checks: [{ id: "bed_fit", status: "pass" }, { id: "wall_thickness", status: "unknown" }] });
  assert.equal(advanceLesson(run, { type: "inspection", state: { ...smaller, revision: 3 } }), run);
  assert.equal(advanceLesson(run, { type: "inspection", state: smaller, checks: [{ id: "wall_thickness", status: "pass" }] }), run);
  assert.equal(advanceLesson(run, { type: "inspection", state: smaller }).stepIndex, 3);
  const changed = { ...smaller, revision: 3 };
  const refreshed = advanceLesson(run, { type: "check_result", state: changed, checks: [{ id: "wall_thickness", status: "unknown" }] });
  assert.equal(refreshed.stepIndex, 2);
  assert.equal(advanceLesson(refreshed, { type: "inspection", state: changed }).stepIndex, 3);
});

test("AI, решатель и relief не завершаются ручными параметрами или пустым событием", () => {
  const ai = runFor("ai-assistant");
  const washer = documentState("washer", { outer_diameter: 20, inner_diameter: 6, height: 4 }, stats([20, 20, 4], 364 * Math.PI));
  assert.equal(advanceLesson(ai, { type: "params", state: washer }), ai);
  assert.equal(advanceLesson(ai, { type: "ai_applied", state: { ...washer, slot: "main" } }), ai);
  const solver = runFor("constraint-solver");
  assert.equal(advanceLesson(solver, { type: "sketch_solved", degrees_of_freedom: 1, state: documentState() }), solver);
  assert.equal(advanceLesson(solver, { type: "sketch_solved", degrees_of_freedom: 0 }), solver);
  const relief = runFor("image-relief");
  const previewStats = stats([40, 20, 6], 3200);
  assert.equal(advanceLesson(relief, { type: "image_preview", stats: previewStats }), relief);
  assert.equal(advanceLesson(relief, { type: "image_preview", state: box20(), stats: previewStats }), relief);
  assert.equal(advanceLesson(relief, { type: "image_preview", state: documentState(), stats: stats([40, 20, 5], 3000) }), relief);
});

test("только ошибка радиуса 50 на сохранённой геометрии выполняет шаг исправления", () => {
  let run = runFor("fillet-fix");
  const bracket = documentState("bracket_l", {}, stats([40, 30, 30], 11000));
  const rounded = { ...bracket, stats: stats([40, 30, 30], 10974.2477796077) };
  run = advanceLesson(run, { type: "params", state: bracket });
  assert.equal(advanceLesson(run, { type: "operation", op: "fillet", radius: 1, state: rounded }), run);
  run = advanceLesson(run, { type: "operation", op: "fillet", radius: 2, state: rounded });
  assert.equal(advanceLesson(run, { type: "error_shown", code: "fillet_failed", state: rounded }), run);
  assert.equal(advanceLesson(run, { type: "error_shown", code: "fillet_failed", radius: 2, state: rounded }), run);
  assert.equal(advanceLesson(run, { type: "error_shown", code: "fillet_failed", radius: 50, state: bracket }), run);
  assert.equal(advanceLesson(run, { type: "error_shown", code: "fillet_failed", radius: 50, state: rounded }).stepIndex, 3);
});

test("пропуск не является освоением; пауза и завершённый урок не принимают события", () => {
  let run = runFor("navigation");
  const paused = { ...run, paused: true };
  assert.equal(advanceLesson(paused, { type: "camera_rotated" }), paused);
  while (run.stepIndex < run.statuses.length) run = skipLessonStep(run);
  assert.equal(lessonMastered(run.statuses), false);
  assert.equal(lessonMastered([]), false);
  assert.equal(advanceLesson(run, { type: "camera_rotated" }), run);
  assert.equal(skipLessonStep(run), run);
});

test("прогресс возобновляется только для совпадающего документа и revision", () => {
  const state = box20();
  let run = advanceLesson(runFor("first-part"), { type: "params", state });
  run = { ...skipLessonStep(run), paused: true };
  const raw = serializeLessonProgress(run, state);
  const restored = restoreLessonRun(run.lesson, 1, lessons.length, raw, state);
  assert.deepEqual(restored?.statuses, ["done", "skipped", "pending", "pending", "pending"]);
  assert.equal(restored?.stepIndex, 2);
  assert.equal(restored?.paused, true);
  assert.equal(lessonMastered(restored!.statuses), false);
  assert.equal(restoreLessonRun(run.lesson, 1, lessons.length, raw, { ...state, revision: state.revision + 1 }), null);
  assert.equal(restoreLessonRun(run.lesson, 1, lessons.length, raw, { ...state, document_instance_id: "new-tutorial" }), null);
  assert.equal(restoreLessonRun(run.lesson, 1, lessons.length, raw, { ...state, slot: "main" }), null);
  assert.equal(restoreLessonRun(run.lesson, 1, lessons.length, serializeLessonProgress(createLessonRun(run.lesson, 1, lessons.length)), state), null);
});

test("повреждённые, старые и чужие progress snapshots игнорируются", () => {
  const run = runFor("navigation");
  const valid = JSON.parse(serializeLessonProgress(run, box20()));
  for (const invalid of [
    null, "{", "[]", "null", JSON.stringify({ ...valid, schema_version: 2 }),
    JSON.stringify({ ...valid, lesson_id: "other" }), JSON.stringify({ ...valid, content_version: 1 }),
    JSON.stringify({ ...valid, statuses: ["done"] }),
    JSON.stringify({ ...valid, statuses: valid.statuses.map(() => "invented") }),
    JSON.stringify({ ...valid, paused: "false" }), JSON.stringify({ ...valid, checkpoint: { revision: -1 } }),
  ]) assert.equal(readLessonProgress(run.lesson, invalid), null);
});
