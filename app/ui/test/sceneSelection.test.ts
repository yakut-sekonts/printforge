import assert from "node:assert/strict";
import test from "node:test";
import { parseMillimeters, partIdForSolid, solidIndicesForParts, togglePartSelection } from "../src/sceneSelection.ts";

const parts = [
  { part_id: "box", solid_count: 1 },
  { part_id: "split", solid_count: 2 },
  { part_id: "tool", solid_count: 1 },
];

test("выбор тела учитывает все solids разделённого тела", () => {
  assert.equal(partIdForSolid(parts, 0), "box");
  assert.equal(partIdForSolid(parts, 2), "split");
  assert.equal(partIdForSolid(parts, 3), "tool");
  assert.equal(partIdForSolid(parts, -1), null);
  assert.equal(partIdForSolid(parts, 4), null);
  assert.deepEqual(solidIndicesForParts(parts, ["split", "tool"]), [1, 2, 3]);
});

test("обычный выбор заменяет набор, Shift добавляет и убирает тело", () => {
  assert.deepEqual(togglePartSelection(["box"], "tool", true), ["box", "tool"]);
  assert.deepEqual(togglePartSelection(["box", "tool"], "box", true), ["tool"]);
  assert.deepEqual(togglePartSelection(["box", "tool"], "split", false), ["split"]);
});

test("точные миллиметры: signed/decimal comma, без неявного нуля и выражений", () => {
  assert.equal(parseMillimeters(" -2,75 "), -2.75);
  assert.equal(parseMillimeters("+.5"), 0.5);
  assert.equal(parseMillimeters("0"), 0);
  for (const raw of ["", " ", "-", "1,2,3", "Infinity", "NaN", "1e309", "0x10", "2+2"]) {
    assert.equal(parseMillimeters(raw), null, raw);
  }
});
