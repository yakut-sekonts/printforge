import assert from "node:assert/strict";
import test from "node:test";
import { addSketchContour, addSketchEntity, arcPolyline, sketchPoints, snapSketchPoint } from "../src/sketchEditing.ts";
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
