import assert from "node:assert/strict";
import test from "node:test";
import { acceptsDocumentState, documentGeometryChanged, faceMeasurementIsCurrent, imageReliefSettingsKey } from "../src/documentState.ts";
import { parameterText, parameterValues, reconcileParameterDrafts, validateParameterValue } from "../src/parameterEditing.ts";
import { evalExpression } from "../src/expr.ts";
import { parseMillimeters } from "../src/sceneSelection.ts";
import type { DocState, ImageReliefSettings, TemplateDef } from "../src/types.ts";

const state: DocState = {
  doc_id: 1, document_instance_id: "old", slot: "main", revision: 8, dirty: true, path: null,
  params: { length: 50, width: 25, height: 20 },
  parts: [
    { part_id: "first", name: "Первая", template: "box", params: { length: 50, width: 25 } },
    { part_id: "second", name: "Вторая", template: "box", params: { height: 35 } },
  ],
  expressions: { "first.width": "length / 2", "second.width": "length / 4", width: "wrong-legacy" },
  stats: null, error: null, can_undo: true, can_redo: false,
};
const template: TemplateDef = {
  template_id: "box", title: "Брусок", command_id: "part.create.box", help_id: "primitivy",
  params: [
    { name: "length", label: "Длина", default: 40, unit: "мм" },
    { name: "width", label: "Ширина", default: 30, unit: "мм" },
    { name: "height", label: "Высота", default: 20, unit: "мм" },
  ],
};

test("измерение грани не подписывается индексом другой выбранной грани", () => {
  assert.equal(faceMeasurementIsCurrent({ faceIndex: 0 }, 0), true);
  assert.equal(faceMeasurementIsCurrent({ faceIndex: 0 }, 1), false);
  assert.equal(faceMeasurementIsCurrent({ faceIndex: 0 }, null), false);
  assert.equal(faceMeasurementIsCurrent({}, 0), false);
  assert.equal(faceMeasurementIsCurrent(null, 0), false);
});

test("повторное открытие того же id с новым instance допускает меньшую revision", () => {
  const opened = { ...state, revision: 1, document_instance_id: "opened" };
  assert.equal(acceptsDocumentState(state, opened), true);
  assert.equal(documentGeometryChanged(state, opened), true);
  assert.equal(acceptsDocumentState(state, { ...state, revision: 7 }), false);
  assert.equal(acceptsDocumentState(state, { ...state, slot: "tutorial", revision: 1 }), true);
  assert.equal(documentGeometryChanged(state, { ...state, dirty: false, path: "file.printforge" }), false);
});

test("черновик соседнего поля не теряется после подтверждения одного поля", () => {
  assert.deepEqual(reconcileParameterDrafts(
    { length: "55", width: "35" }, { length: "40", width: "30" }, { length: "55", width: "30" },
  ), { length: "55", width: "35" });
  assert.deepEqual(reconcileParameterDrafts(
    { length: "55", width: "35" }, { length: "55", width: "30" }, { length: "55", width: "35" },
  ), { length: "55", width: "35" });
});

test("нижняя граница каталога разрешает ноль только подходящим параметрам", () => {
  const zeroAllowed = { name: "hole_diameter", label: "Диаметр отверстия", unit: "мм", min: 0, default: 4 };
  assert.doesNotThrow(() => validateParameterValue(0, zeroAllowed));
  assert.doesNotThrow(() => validateParameterValue(0.1, { ...zeroAllowed, min: 0.1 }));
  assert.throws(() => validateParameterValue(-1, zeroAllowed), /Минимальное значение/);
  assert.throws(() => validateParameterValue(0, { ...zeroAllowed, min: 0.1 }), /Минимальное значение/);
  assert.throws(() => validateParameterValue(Number.NaN, zeroAllowed), /конечным числом/);
  assert.throws(() => validateParameterValue(0, undefined), /больше нуля/);
});

test("контекст выражения включает defaults выбранной детали, но не параметры соседа", () => {
  assert.deepEqual(parameterValues(state, template, "second"), { length: 40, width: 30, height: 35 });
  assert.equal(evalExpression("length / 4", parameterValues(state, template, "second")), 10);
  assert.equal(evalExpression("длина / 2", parameterValues(state, template, "first")), 25);
  assert.equal(parameterText(state, "first", "width", 25), "length / 2");
  assert.equal(parameterText(state, "second", "width", 30), "length / 4");
  assert.equal(parameterText({ ...state, expressions: { width: "legacy" } }, "second", "width", 30), "30");
});

test("выражения и числовые поля не принимают пустоту, NaN и подмену нулём", () => {
  for (const invalid of ["", "abc", "1/0", "2**3", "(20+5", "Infinity", "constructor"]) {
    assert.throws(() => evalExpression(invalid, { length: 40 }));
  }
  for (const invalid of ["", "abc", "Infinity", "NaN", "1e2", "10 мм"]) assert.equal(parseMillimeters(invalid), null);
  assert.equal(parseMillimeters("4,5"), 4.5);
  assert.equal(parseMillimeters("0"), 0);
});

test("Apply рельефа привязан ко всем показанным настройкам, а не только пути", () => {
  const settings: ImageReliefSettings = {
    path: "gradient.png", model: "heightmap-luminance-v1", seed: 42, width_mm: 40,
    relief_height: 4, base_thickness: 2, samples: 64, noise_strength: 0, invert: false,
  };
  const key = imageReliefSettingsKey(settings);
  assert.equal(imageReliefSettingsKey({ ...settings }), key);
  for (const update of [
    { path: "other.png" }, { seed: 43 }, { width_mm: 80 }, { relief_height: 8 },
    { base_thickness: 3 }, { samples: 192 }, { noise_strength: 0.01 }, { invert: true },
  ]) assert.notEqual(imageReliefSettingsKey({ ...settings, ...update }), key);
});
