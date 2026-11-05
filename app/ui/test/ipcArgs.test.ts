import assert from "node:assert/strict";
import test from "node:test";
import { nativeIpcArgs } from "../src/ipcArgs.ts";

test("native argument names match default Tauri camelCase command parameters", () => {
  const faceRef = {
    kind: "planar",
    solid_index: 1,
    center: [0, 0, 20],
    normal: [0, 0, 1],
    area: 1200,
  };
  const args = {
    target_id: "part-1",
    face_ref: faceRef,
    part_id: "part-2",
    keep_tool: false,
    distance: 2,
  };
  const converted = nativeIpcArgs(args);
  assert.deepEqual(converted, {
    targetId: "part-1",
    faceRef,
    partId: "part-2",
    keepTool: false,
    distance: 2,
  });
  assert.equal(converted?.faceRef, faceRef);
  assert.equal(faceRef.kind, "planar");
  assert.equal(faceRef.solid_index, 1);
  assert.equal(args.target_id, "part-1");
  assert.equal(Object.hasOwn(args, "targetId"), false);
});

test("nested CAD parameter identifiers and plan operations remain unchanged", () => {
  const params = { hole_diameter: 4, hole_offset: 10 };
  const operations = [{
    command_id: "parameter.set",
    target_id: "part-1",
    parameters: { name: "hole_diameter", value: 5 },
  }];
  const converted = nativeIpcArgs({ params, operations, base_revision: 7 });
  assert.deepEqual(converted, { params, operations, baseRevision: 7 });
  assert.equal(converted?.params, params);
  assert.equal(converted?.operations, operations);
  assert.equal(params.hole_diameter, 4);
  assert.equal(operations[0].target_id, "part-1");
});

test("existing AI camelCase arguments are idempotent", () => {
  const args = {
    taskId: "task-1",
    baseUrl: "http://localhost:11434",
    apiKey: "test-key",
    clearApiKey: false,
    documentInstanceId: 3,
    planHash: "hash",
  };
  assert.deepEqual(nativeIpcArgs(args), args);
  assert.deepEqual(nativeIpcArgs(nativeIpcArgs(args)), args);
});

test("missing arguments and optional undefined values are preserved", () => {
  assert.equal(nativeIpcArgs(), undefined);
  assert.equal(nativeIpcArgs(undefined), undefined);
  assert.deepEqual(nativeIpcArgs({}), {});
  const converted = nativeIpcArgs({ unit_scale: undefined });
  assert.deepEqual(converted, { unitScale: undefined });
  assert.equal(Object.hasOwn(converted!, "unitScale"), true);
});
