import assert from "node:assert/strict";
import test from "node:test";
import {
  analyzeFace, pushPullDelta, pushPullValue, resolveFaceEditTarget,
  resolveFaceFeatureTarget, resolveGenericFaceEditTarget, resolveSheetBendTarget,
} from "../src/faceEditing.ts";
import type { MeshData, PartDef, Point3, TemplateDef } from "../src/types.ts";

function boxScene(boxes: Array<{ min: Point3; max: Point3 }>): MeshData {
  const mesh: MeshData = {
    vertex_count: 0,
    triangle_count: 0,
    positions: [],
    indices: [],
    face_ranges: [],
  };
  for (const [solidIndex, box] of boxes.entries()) {
    const [minX, minY, minZ] = box.min;
    const [maxX, maxY, maxZ] = box.max;
    const vertices = [
      [minX, minY, minZ], [maxX, minY, minZ],
      [maxX, maxY, minZ], [minX, maxY, minZ],
      [minX, minY, maxZ], [maxX, minY, maxZ],
      [maxX, maxY, maxZ], [minX, maxY, maxZ],
    ];
    const triangles = [
      [0, 2, 1, 0, 3, 2], [4, 5, 6, 4, 6, 7],
      [0, 4, 7, 0, 7, 3], [1, 2, 6, 1, 6, 5],
      [0, 1, 5, 0, 5, 4], [3, 7, 6, 3, 6, 2],
    ];
    const vertexOffset = mesh.positions.length / 3;
    mesh.positions = [...mesh.positions, ...vertices.flat()];
    for (const triangle of triangles) {
      mesh.face_ranges.push({
        face_index: mesh.face_ranges.length,
        solid_index: solidIndex,
        tri_start: mesh.indices.length / 3,
        tri_count: 2,
      });
      mesh.indices = [...mesh.indices, ...triangle.map((vertex) => vertex + vertexOffset)];
    }
  }
  mesh.vertex_count = mesh.positions.length / 3;
  mesh.triangle_count = mesh.indices.length / 3;
  return mesh;
}

const boxPart: PartDef = {
  part_id: "box-a",
  name: "Первый брусок",
  template: "box",
  params: { length: 10, width: 10, height: 5 },
};

const boxTemplate: TemplateDef = {
  template_id: "box",
  title: "Параллелепипед",
  command_id: "part.create.box",
  help_id: "primitivy",
  params: [],
};

test("граница и размер выбранного тела не зависят от второй детали", () => {
  const mesh = boxScene([
    { min: [0, 0, 0], max: [10, 10, 5] },
    { min: [100, 100, 0], max: [120, 120, 20] },
  ]);
  assert.equal(analyzeFace(mesh, 1)?.atBoundary, false);
  const face = analyzeFace(mesh, 1, [0]);
  assert.equal(face?.atBoundary, true);
  assert.equal(face?.axisSpan, 5);
  const target = resolveFaceEditTarget(mesh, 1, boxPart, boxTemplate, [0]);
  assert.equal(target?.parameter, "height");
  assert.equal(target?.current, 5);
  assert.equal(target?.mode, "parameter");
  assert.equal(analyzeFace(mesh, 1, [1]), null);
  assert.equal(analyzeFace(mesh, 1, []), null);
});

test("якоря face feature и bend считаются относительно выбранного тела", () => {
  const mesh = boxScene([
    { min: [30, -20, 0], max: [40, -10, 5] },
    { min: [100, 100, 0], max: [120, 120, 20] },
  ]);
  assert.deepEqual(resolveFaceFeatureTarget(mesh, 1, "box-a", [0])?.anchor, [0, 0]);
  assert.deepEqual(resolveSheetBendTarget(mesh, 1, "box-a", [0])?.anchor, [0, 0]);
  assert.equal(resolveFaceFeatureTarget(mesh, 1, "box-a", [1]), null);
});

test("центральная верхняя грань остаётся доступной для следующего изгиба после подъёма фланца", () => {
  const mesh = boxScene([
    { min: [-20, -20, 0], max: [20, 20, 6] },
    { min: [20, -20, 0], max: [26, 20, 30] },
  ]);
  const target = resolveSheetBendTarget(mesh, 1, "plate", [0, 1]);
  assert.ok(target);
  assert.equal(target.atBoundary, false);
  assert.equal(target.axis, "z");
  assert.equal(target.side, 1);
  assert.equal(resolveFaceFeatureTarget(mesh, 1, "plate", [0, 1]), null);
  assert.equal(resolveSheetBendTarget(mesh, 0, "plate", [0, 1]), null);
});

test("bounds включают все solids выбранной детали", () => {
  const mesh = boxScene([
    { min: [0, 0, 0], max: [10, 10, 5] },
    { min: [20, 0, 0], max: [30, 10, 5] },
    { min: [100, 100, 0], max: [120, 120, 20] },
  ]);
  const target = resolveFaceFeatureTarget(mesh, 1, "pair", [0, 1]);
  assert.ok(target);
  assert.ok(Math.abs(target.anchor[0] + 10) < 1e-12);
  assert.ok(Math.abs(target.anchor[1]) < 1e-12);
  assert.equal(target?.axisSpan, 5);
});

test("generic offset доступен на плоской грани внутри bounds детали", () => {
  const mesh = boxScene([
    { min: [0, 0, 0], max: [10, 10, 5] },
    { min: [20, 0, 0], max: [30, 10, 20] },
  ]);
  const faceRef = {
    kind: "planar" as const,
    solid_index: 0,
    center: [5, 5, 5] as Point3,
    normal: [0, 0, 1] as Point3,
    area: 100,
  };
  mesh.face_ranges[1].face_ref = faceRef;
  const target = resolveGenericFaceEditTarget(mesh, 1, "pair", [0, 1]);
  assert.ok(target);
  assert.equal(target.atBoundary, false);
  assert.equal(target.mode, "offset");
  assert.equal(target.parameter, "");
  assert.equal(target.faceRef, faceRef);
  assert.equal(target.current, 0);
  assert.equal(target.minimum, -Infinity);
  assert.equal(target.symmetric, false);
  assert.equal(pushPullValue(target, -2.5), -2.5);
  assert.equal(pushPullDelta(target, 3.5), 3.5);
  assert.equal(resolveGenericFaceEditTarget(mesh, 1, "other", [1]), null);
  assert.equal(resolveGenericFaceEditTarget(mesh, 0, "pair", [0, 1]), null);
});

test("generic offset принимает наклонную плоскую грань", () => {
  const mesh: MeshData = {
    vertex_count: 4,
    triangle_count: 2,
    positions: [0, 0, 0, 10, 0, 10, 10, 10, 10, 0, 10, 0],
    indices: [0, 1, 2, 0, 2, 3],
    face_ranges: [{
      face_index: 0,
      solid_index: 0,
      tri_start: 0,
      tri_count: 2,
      face_ref: {
        kind: "planar",
        solid_index: 0,
        center: [5, 5, 5],
        normal: [-Math.SQRT1_2, 0, Math.SQRT1_2],
        area: 100 * Math.SQRT2,
      },
    }],
  };
  const target = resolveGenericFaceEditTarget(mesh, 0, "slope", [0]);
  assert.ok(target);
  assert.equal(target.axis, null);
  assert.equal(target.planar, true);
  assert.ok(Math.abs(target.normal[0] + Math.SQRT1_2) < 1e-12);
  (mesh.positions as number[])[11] = 2;
  assert.equal(resolveGenericFaceEditTarget(mesh, 0, "slope", [0]), null);
});

test("generic preview использует точную normal из BRep metadata", () => {
  const mesh = boxScene([{ min: [0, 0, 0], max: [10, 10, 5] }]);
  const angle = Math.PI / 36;
  const positions = [...mesh.positions];
  for (let offset = 0; offset < positions.length; offset += 3) {
    const previousX = positions[offset];
    const previousZ = positions[offset + 2];
    positions[offset] = previousX * Math.cos(angle) + previousZ * Math.sin(angle);
    positions[offset + 2] = -previousX * Math.sin(angle) + previousZ * Math.cos(angle);
  }
  mesh.positions = positions;
  mesh.face_ranges[1].face_ref = {
    kind: "planar",
    solid_index: 0,
    center: [5 * Math.cos(angle) + 5 * Math.sin(angle), 5, -5 * Math.sin(angle) + 5 * Math.cos(angle)],
    normal: [Math.sin(angle), 0, Math.cos(angle)],
    area: 100,
  };
  const target = resolveGenericFaceEditTarget(mesh, 1, "tilt", [0]);
  assert.ok(target);
  assert.ok(Math.abs(target.normal[0] - Math.sin(angle)) < 1e-12);
  assert.ok(Math.abs(target.normal[2] - Math.cos(angle)) < 1e-12);
});
