import assert from "node:assert/strict";
import test from "node:test";
import { addSketchContour, addSketchEntity, arcPolyline, checkpointSketchContour, describeSketchConstraint, pointsAfterToolChange, setSketchDimension, sketchDimensionValue, sketchForRadiusDrag, sketchPairActions, sketchPoints, snapSketchPoint } from "../src/sketchEditing.ts";
import { changeLocalFeature, findSmallerFeature, localFeatureValue } from "../src/localFeatures.ts";
import type { ConstrainedSketch } from "../src/types.ts";

const empty: ConstrainedSketch = { entities: [], constraints: [], regions: [] };

test("inferred sketch constraints preserve intent without modifying the input", () => {
  const first = addSketchEntity(empty, { id: "a", type: "line", start: [0, 0], end: [10, 0.1] });
  assert.equal(first.constraints[0].type, "horizontal");
  const second = addSketchEntity(first, { id: "b", type: "line", start: [10, 0.1], end: [10, 8] });
  assert.ok(second.constraints.some((constraint) => constraint.type === "coincident"));
  assert.ok(second.constraints.some((constraint) => constraint.type === "vertical"));
  assert.equal(empty.entities.length, 0);
  assert.equal(first.entities.length, 1);
});

test("point snapping includes arc midpoints and never changes the caller's coordinate", () => {
  const sketch = addSketchEntity(empty, { id: "arc", type: "arc", start: [-5, 0], mid: [0, 5], end: [5, 0] });
  const point: [number, number] = [0.1, 5.1];
  assert.deepEqual(snapSketchPoint(sketch, point, 1).point, [0, 5]);
  assert.deepEqual(snapSketchPoint(sketch, point, 1).ref, ["arc", "mid"]);
  assert.deepEqual(point, [0.1, 5.1]);
  assert.equal(sketchPoints(sketch.entities[0]).length, 3);
});

test("outer contours and holes are explicit and immutable", () => {
  assert.throws(() => addSketchContour(empty, "hole", true), /внешний контур/);
  const outside = addSketchContour(empty, ["a", "b", "c"], false);
  const inside = addSketchContour(outside, "circle", true);
  assert.deepEqual(inside.regions?.[0].holes, ["circle"]);
  assert.deepEqual(outside.regions?.[0].holes, []);
});

test("invalid circles, zero lines and duplicate IDs are rejected", () => {
  for (const radius of [0, -1, NaN, Infinity]) assert.throws(() => addSketchEntity(empty, { id: "c", type: "circle", center: [0, 0], radius }));
  assert.throws(() => addSketchEntity(empty, { id: "line", type: "line", start: [0, 0], end: [0, 0] }));
  const sketch = addSketchEntity(empty, { id: "c", type: "circle", center: [0, 0], radius: 1 });
  assert.throws(() => addSketchEntity(sketch, sketch.entities[0]));
});

test("arc display passes through both endpoints and follows the middle half-plane", () => {
  const points = arcPolyline({ id: "arc", type: "arc", start: [-5, 0], mid: [0, 5], end: [5, 0] });
  assert.ok(Math.abs(points[0][0] + 5) < 1e-9);
  assert.ok(Math.abs(points[48][0] - 5) < 1e-9);
  assert.ok(points[24][1] > 4.99);
  assert.ok(points.every((point) => point[1] > -1e-8));
});

test("local editing changes only its chosen profile field", () => {
  const changes = { profile: { kind: "circle", center: [3, 4], diameter: 6 }, depth: 5 };
  assert.equal(localFeatureValue(changes, "diameter"), 6);
  assert.equal(localFeatureValue(changes, "u"), 3);
  const edited = changeLocalFeature(changes, "diameter", 8);
  assert.deepEqual(edited, { profile: { kind: "circle", center: [3, 4], diameter: 8 }, depth: 5 });
  assert.equal(changes.profile.diameter, 6);
  assert.deepEqual((changeLocalFeature(changes, "v", -2).profile as { center: number[] }).center, [3, -2]);
  assert.throws(() => changeLocalFeature(changes, "radius", NaN));
});

test("suggestion is returned only after full candidate validation", async () => {
  const action = { type: "append" as const, operation: { op: "fillet", radius: 32 } };
  const attempted: number[] = [];
  const result = await findSmallerFeature(action, "radius", 32, async (candidate) => {
    assert.equal(candidate.type, "append");
    if (candidate.type !== "append") return;
    const value = candidate.operation.radius as number;
    attempted.push(value);
    if (value > 4) throw { code: "fillet_failed" };
  }, () => false);
  assert.equal(result, 4); assert.deepEqual(attempted, [16, 8, 4]);
  assert.equal(action.operation.radius, 32);
});

test("suggestion has a bounded search and aborts on unrelated errors", async () => {
  let attempts = 0;
  const action = { type: "edit" as const, index: 0, changes: { distance: 1000 } };
  assert.equal(await findSmallerFeature(action, "distance", 1000, async () => { attempts += 1; throw { code: "chamfer_failed" }; }, () => false), null);
  assert.equal(attempts, 6);
  await assert.rejects(findSmallerFeature(action, "distance", 1000, async () => { throw { code: "document_changed" }; }, () => false));
  assert.equal(await findSmallerFeature(action, "distance", 1000, async () => { throw Error("must not run"); }, () => true), null);
});


test("editing a sketch dimension replaces the matching value without changing other constraints", () => {
  const circle = { id: "circle", type: "circle" as const, center: [0, 0] as [number, number], radius: 3 };
  const original = { ...empty, entities: [circle], constraints: [{ type: "fix" as const, entity: "circle" }] };
  const first = setSketchDimension(original, "circle", "radius", 3.125);
  const second = setSketchDimension(first, "circle", "radius", 5);
  assert.deepEqual(second.constraints, [{ type: "fix", entity: "circle" }, { type: "dimension", entity: "circle", kind: "radius", value: 5 }]);
  assert.equal(first.constraints.length, 2);
  assert.equal(sketchDimensionValue(first, circle), 3.125);
  assert.equal(sketchDimensionValue(second, circle), 5);
  assert.equal(setSketchDimension(second, "circle", "radius", 5), second);
  assert.throws(() => setSketchDimension(second, "circle", "radius", NaN));
  assert.throws(() => setSketchDimension(second, "circle", "radius", 0));
});

test("dimension edits preserve other entities and repair duplicate values from older sketches", () => {
  const sketch: ConstrainedSketch = { ...empty, constraints: [
    { type: "dimension", kind: "length", entity: "a", value: 10 },
    { type: "dimension", kind: "radius", entity: "b", value: 3 },
    { type: "dimension", kind: "length", entity: "a", value: 12 },
  ] };
  const result = setSketchDimension(sketch, "a", "length", 20);
  assert.deepEqual(result.constraints.map((item) => item.type === "dimension" ? item.value : null), [20, 3, 20]);
  assert.deepEqual(sketch.constraints.map((item) => item.type === "dimension" ? item.value : null), [10, 3, 12]);
});


test("sketch pair actions match the solver's supported entity types", () => {
  const line = { id: "l", type: "line" as const, start: [0, 0] as [number, number], end: [5, 0] as [number, number] };
  const circle = { id: "c", type: "circle" as const, center: [0, 0] as [number, number], radius: 3 };
  const arc = { id: "a", type: "arc" as const, start: [0, 0] as [number, number], mid: [1, 1] as [number, number], end: [2, 0] as [number, number] };
  assert.deepEqual(sketchPairActions(line, line), { equal: true, directional: true });
  assert.deepEqual(sketchPairActions(circle, circle), { equal: true, directional: false });
  assert.deepEqual(sketchPairActions(line, circle), { equal: false, directional: false });
  assert.deepEqual(sketchPairActions(arc, arc), { equal: false, directional: false });
  assert.deepEqual(sketchPairActions(line, undefined), { equal: false, directional: false });
});

test("sketch constraints show meaningful labels and values", () => {
  assert.equal(describeSketchConstraint({ type: "dimension", kind: "radius", entity: "c", value: 5 }), "Радиус · c · 5 мм");
  assert.equal(describeSketchConstraint({ type: "horizontal", entity: "l" }), "Горизонтально · l");
  assert.equal(describeSketchConstraint({ type: "equal", a: "a", b: "b" }), "Равные размеры · a / b");
});


test("unfinished contour checkpoint preserves the prior sketch and undo history", () => {
  const completed = addSketchContour(addSketchEntity(empty, { id: "c", type: "circle", center: [0, 0], radius: 4 }), "c", false);
  const history = [empty];
  const checkpoint = checkpointSketchContour(completed, history);
  const unfinished = addSketchEntity(completed, { id: "l", type: "line", start: [5, 0], end: [8, 0] });
  history.push(completed);
  assert.equal(unfinished.entities.length, 2);
  assert.deepEqual(checkpoint.sketch, completed);
  assert.deepEqual(checkpoint.undo, [empty]);
  assert.deepEqual(checkpoint.sketch.regions?.[0].outer, "c");
});


test("switching a contour tool keeps the shared endpoint and discards unfinished arc points", () => {
  const endpoint: [number, number] = [4, 2];
  const unfinished: [number, number] = [7, 5];
  const points: [number, number][] = [endpoint, unfinished];
  assert.deepEqual(pointsAfterToolChange(points, true), [endpoint]);
  assert.deepEqual(pointsAfterToolChange(points, false), []);
  assert.deepEqual(points, [endpoint, unfinished]);
});


test("radius dragging updates an existing dimension without adding one to a free circle", () => {
  const free: ConstrainedSketch = { ...empty, constraints: [{ type: "fix", point: ["c", "center"], value: [0, 0] }] };
  assert.equal(sketchForRadiusDrag(free, "c", 7), free);
  const sized = setSketchDimension(free, "c", "radius", 5);
  const candidate = sketchForRadiusDrag(sized, "c", 7);
  assert.deepEqual(candidate.constraints, [{ type: "fix", point: ["c", "center"], value: [0, 0] }, { type: "dimension", entity: "c", kind: "radius", value: 7 }]);
  assert.equal(sketchDimensionValue(sized, { id: "c", type: "circle", center: [0, 0], radius: 5 }), 5);
  assert.equal(sketchForRadiusDrag(sized, "other", 7), sized);
});
