import assert from "node:assert/strict";
import test from "node:test";
import { geometryProgressLabel } from "../src/geometryControl.ts";

test("показывает детерминированное время длительной geometry operation", () => {
  assert.equal(geometryProgressLabel(0, false), "Вычисление…");
  assert.equal(geometryProgressLabel(3.9, false), "Вычисление · 3 с…");
  assert.equal(geometryProgressLabel(-2, false), "Вычисление…");
});

test("состояние отмены имеет приоритет над временем", () => {
  assert.equal(geometryProgressLabel(45, true), "Останавливаем вычисление…");
});
