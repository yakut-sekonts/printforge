import assert from "node:assert/strict";
import test from "node:test";
import { constrainedSize, deformPositions, editableParameters, edgeDesignerAction, operationName, PreviewQueue, snapTranslation } from "../src/designer.ts";

test("edge actions use the kernel part_id contract for both fillet and chamfer", () => {
  const edge = { solid_index: 0, kind: "LINE", length: 10, midpoint: [0, 0, 0] as [number, number, number] };
  assert.deepEqual(edgeDesignerAction("fillet", edge, 2, "one"), { type: "append", operation: { op: "fillet", part_id: "one", edge_ref: edge, radius: 2 } });
  assert.deepEqual(edgeDesignerAction("chamfer", edge, 3, "one"), { type: "append", operation: { op: "chamfer", part_id: "one", edge_ref: edge, distance: 3 } });
});

test("radial and uniform constraints preserve circular primitives", () => {
  assert.deepEqual(constrainedSize([20, 20, 30], 0, 40, "radial"), [40, 40, 30]);
  assert.deepEqual(constrainedSize([20, 20, 30], 2, 40, "radial"), [20, 20, 40]);
  assert.deepEqual(constrainedSize([20, 20, 20], 2, 40, "uniform"), [40, 40, 40]);
  assert.deepEqual(constrainedSize([20, 20, 30], 0, 40, "free"), [40, 20, 30]);
  for (const value of [0, -1, NaN, Infinity]) assert.throws(() => constrainedSize([1, 1, 1], 0, value));
});

test("snapping covers grid, centers and outer surfaces without altering other axes", () => {
  const bounds = [0, 0, 0, 10, 10, 10];
  assert.deepEqual(snapTranslation(bounds, [], 0, 2.4, 1, 1), { delta: 2, label: "Сетка 1 мм" });
  assert.equal(snapTranslation(bounds, [[20, 0, 0, 30, 10, 10]], 0, 9.7, 1, 1).delta, 10);
  assert.equal(snapTranslation(bounds, [[20, 0, 0, 30, 10, 10]], 0, 24.8, 1, 1).delta, 25);
  assert.equal(snapTranslation(bounds, [], 0, -2.36, 0.1, 0).delta, -2.4000000000000004);
});

test("soft deformation copies input and smoothly vanishes at brush boundary", () => {
  const original = [0, 0, 0, 5, 0, 0, 10, 0, 0, 20, 0, 0];
  const output = deformPositions(original, [0, 0, 0], [0, 0, 4], 10);
  assert.equal(output[2], 4);
  assert.equal(output[5], 2.25);
  assert.equal(output[8], 0);
  assert.equal(output[11], 0);
  assert.equal(original[2], 0);
  assert.throws(() => deformPositions(original, [0, 0, 0], [0, 0, 1], 0));
});

test("named history exposes parameters but not identity or geometry references", () => {
  const operation = { op: "fillet", target_id: "one", radius: 2, edge_ref: { solid_index: 0, kind: "LINE", length: 10, midpoint: [0, 0, 0] as [number, number, number] } };
  assert.equal(operationName(operation), "Скругление · 2 мм");
  assert.deepEqual(editableParameters(operation), { radius: 2 });
  assert.deepEqual(editableParameters({ op: "step_source" }), {});
});

test("Preview queue serializes work and discards stale success and failure", async () => {
  const queue = new PreviewQueue();
  const seen: number[] = [];
  const errors: unknown[] = [];
  let release!: (value: number) => void;
  queue.schedule(() => new Promise<number>((resolve) => { release = resolve; }), (value) => seen.push(value), (error) => errors.push(error));
  await Promise.resolve();
  queue.schedule(async () => 2, (value) => seen.push(value), (error) => errors.push(error));
  release(1);
  await queue.drain();
  assert.deepEqual(seen, [2]);
  queue.schedule(async () => { throw new Error("stale"); }, () => {}, (error) => errors.push(error));
  queue.invalidate();
  await queue.drain();
  assert.deepEqual(errors, []);
});

test("invalidating an in-flight Preview prevents painting after commit", async () => {
  const queue = new PreviewQueue();
  let release!: (value: number) => void;
  let painted = false;
  queue.schedule(() => new Promise<number>((resolve) => { release = resolve; }), () => { painted = true; }, () => {});
  await Promise.resolve();
  queue.invalidate(); release(1); await queue.drain();
  assert.equal(painted, false);
});
