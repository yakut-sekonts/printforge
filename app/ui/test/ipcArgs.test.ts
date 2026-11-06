import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";
import { clearMocks, mockIPC } from "@tauri-apps/api/mocks";
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

test("measurement IPC uses measureType and preserves nested extra coordinates", () => {
  const extra = { face_index: 2, p0: [0, 0, 0], p1: [3, 4, 0] };
  const converted = nativeIpcArgs({ measure_type: "distance", extra });
  assert.deepEqual(converted, { measureType: "distance", extra });
  assert.equal(converted?.extra, extra);
  assert.equal(extra.face_index, 2);
});

test("backend SDK sends native contracts and retains flat shim measurement arguments", async () => {
  const hooks = registerHooks({
    resolve(specifier, context, nextResolve) {
      if (specifier.startsWith("./") && context.parentURL?.includes("/src/")) {
        return nextResolve(`${specifier}.ts`, context);
      }
      return nextResolve(specifier, context);
    },
  });
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  globalThis.window = { __TAURI__: {} };
  const requests: { command: string; args: unknown }[] = [];
  mockIPC((command, args) => {
    requests.push({ command, args });
    return {};
  });
  try {
    const { backend } = await import("../src/backend.ts");
    const resize = { target_id: "part-1", size: [60, 40, 20] as [number, number, number], anchor: [-1, 1, -1] as [-1, 1, -1] };
    await backend.docResizeBody(resize);
    assert.deepEqual(requests.pop(), { command: "doc_resize_body", args: { targetId: "part-1", size: resize.size, anchor: resize.anchor } });
    const source = { revision: 9, document_instance_id: 7 } as import("../src/types.ts").DocState;
    const action = { type: "append" as const, operation: { op: "resize_parametric", target_id: "part-1", size: [60, 40, 20], anchor: [-1, 1, -1] } };
    await backend.docDesignerPreview(action, source);
    assert.deepEqual(requests.pop(), { command: "doc_designer_action", args: { action, expectedRevision: 9, expectedInstance: 7, preview: true } });
    await backend.docDesignerAction(action, source);
    assert.deepEqual(requests.pop(), { command: "doc_designer_action", args: { action, expectedRevision: 9, expectedInstance: 7, preview: false } });
    const measurement = { type: "distance" as const, face_index: 2, p0: [0, 0, 0] as [number, number, number], p1: [3, 4, 0] as [number, number, number] };
    await backend.measure(measurement);
    assert.deepEqual(requests.pop(), {
      command: "measure", args: { measureType: "distance", extra: { face_index: 2, p0: [0, 0, 0], p1: [3, 4, 0] } },
    });
    await backend.docSaveMain("/tmp/main.printforge");
    assert.deepEqual(requests.pop(), { command: "doc_save_main", args: { path: "/tmp/main.printforge" } });
    await backend.docConfirmClose(7, 12, false);
    assert.deepEqual(requests.pop(), {
      command: "doc_confirm_close", args: { expectedDocumentInstanceId: 7, expectedRevision: 12, discard: false },
    });
    await backend.docImageReliefApply({
      path: "/tmp/image.png", model: "heightmap-luminance-v1", seed: 42,
      width_mm: 40, relief_height: 4, base_thickness: 2, samples: 24, noise_strength: 0, invert: false,
    }, "source-hash", "settings-hash");
    assert.deepEqual(requests.pop(), {
      command: "doc_image_relief_apply", args: {
        path: "/tmp/image.png", model: "heightmap-luminance-v1", seed: 42,
        widthMm: 40, reliefHeight: 4, baseThickness: 2, samples: 24, noiseStrength: 0, invert: false,
        expectedSha256: "source-hash", expectedSettingsSha256: "settings-hash",
      },
    });
    delete globalThis.window.__TAURI__;
    globalThis.fetch = async (url, init) => {
      requests.push({ command: String(url), args: JSON.parse(String(init?.body)) });
      return new Response("{}", { status: 200 });
    };
    await backend.measure(measurement);
    assert.deepEqual(requests.pop(), { command: "http://localhost:8787/api/measure", args: measurement });
    await backend.docResizeBody(resize);
    assert.deepEqual(requests.pop(), { command: "http://localhost:8787/api/doc_resize_body", args: resize });
  } finally {
    clearMocks();
    globalThis.window = previousWindow;
    globalThis.fetch = previousFetch;
    hooks.deregister();
  }
});
