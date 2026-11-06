import assert from "node:assert/strict";
import test from "node:test";
import { resizeAnchor, resizeChanged, resizeDirection, resizedDimensions, sizeLabel } from "../src/bodyResizing.ts";
import type { ResizeHandle, Size3 } from "../src/bodyResizing.ts";

const size: Size3 = [60, 40, 20];
const corner: ResizeHandle = { corner: [1, 1, 1], axis: null };

test("corner drag scales all three dimensions proportionally", () => {
  assert.deepEqual(resizedDimensions(size, corner, 30), [90, 60, 30]);
  assert.deepEqual(resizeAnchor(corner), [-1, -1, -1]);
  assert.deepEqual(size, [60, 40, 20]);
});

test("all eight corners preserve the opposite anchor and outward direction", () => {
  for (const sideX of [-1, 1] as const) for (const sideY of [-1, 1] as const) for (const sideZ of [-1, 1] as const) {
    const handle: ResizeHandle = { axis: null, corner: [sideX, sideY, sideZ] };
    assert.deepEqual(resizeAnchor(handle), [-sideX, -sideY, -sideZ]);
    assert.deepEqual(resizeDirection(size, handle), [sideX, sideY * 2 / 3, sideZ / 3]);
    assert.deepEqual(resizedDimensions(size, handle, 30), [90, 60, 30]);
  }
});

test("side handles stretch only the selected axis, including negative sides", () => {
  for (const axis of [0, 1, 2] as const) for (const side of [-1, 1] as const) {
    const handle: ResizeHandle = { axis, corner: [1, 1, 1] };
    handle.corner[axis] = side;
    const result = resizedDimensions(size, handle, 10);
    assert.equal(result[axis], size[axis] + 10);
    assert.equal(resizeAnchor(handle)[axis], -side);
    for (const other of [0, 1, 2]) if (other !== axis) assert.equal(result[other], size[other]);
  }
});

test("normal drag snaps to 1 mm and Shift to 0.1 mm", () => {
  const handle: ResizeHandle = { axis: 0, corner: [1, 1, 1] };
  assert.equal(resizedDimensions(size, handle, 2.36)[0], 62);
  assert.equal(resizedDimensions(size, handle, 2.36, true)[0], 62.4);
  assert.equal(resizedDimensions(size, handle, -2.5)[0], 57);
});

test("dragging through the fixed corner never mirrors or collapses the body", () => {
  const smallest = resizedDimensions(size, corner, -1000);
  assert.equal(smallest[2], 0.1);
  assert.ok(Math.abs(smallest[0] / smallest[1] - 1.5) < 1e-12);
  assert.equal(resizedDimensions(size, { axis: 1, corner: [-1, -1, -1] }, -1000)[1], 0.1);
});

test("no movement is not a document edit", () => {
  assert.equal(resizeChanged(size, resizedDimensions(size, corner, 0.2)), false);
  assert.equal(resizeChanged(size, resizedDimensions(size, corner, 2)), true);
  assert.equal(sizeLabel([60, 40.12345, 20]), "60 × 40.12 × 20 мм");
});

test("existing thin bodies are not enlarged by a zero or inward drag", () => {
  const thin: Size3 = [40, 20, 0.05];
  assert.deepEqual(resizedDimensions(thin, corner, 0.1), thin);
  assert.deepEqual(resizedDimensions(thin, corner, -1000), thin);
  assert.deepEqual(resizedDimensions(thin, { axis: 2, corner: [1, 1, 1] }, -1000), thin);
});

test("nonfinite or nonpositive dimensions and movement are rejected", () => {
  for (const invalid of [NaN, Infinity, -Infinity]) assert.throws(() => resizedDimensions(size, corner, invalid));
  for (const invalid of [0, -1, NaN, Infinity]) assert.throws(() => resizedDimensions([invalid, 2, 3], corner, 1));
});
