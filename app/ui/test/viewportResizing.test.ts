import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";
import * as THREE from "three";

const hooks = registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("./") && context.parentURL?.includes("/app/ui/src/") && !/\.[a-z]+$/.test(specifier)) {
      return nextResolve(`${specifier}.ts`, context);
    }
    return nextResolve(specifier, context);
  },
});
const { Viewport } = await import("../src/viewport.ts");
const previousDocument = globalThis.document;
globalThis.document = {
  createElement: () => ({ width: 1, height: 1, getContext: () => ({
    measureText: (text: string) => ({ width: text.length * 10 }), scale() {}, fillText() {},
  }) }),
};
test.after(() => { globalThis.document = previousDocument; hooks.deregister(); });

function fixture() {
  const viewport = Object.create(Viewport.prototype) as any;
  const captured = new Set<number>();
  const commits: unknown[] = [];
  const previews: unknown[] = [];
  const original = new THREE.BufferGeometry();
  original.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, 10, 0, 0, 0, 30, -20, 100, 100, 100], 3));
  original.setIndex([0, 1, 2]);
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
  camera.position.set(100, 100, 100); camera.lookAt(0, 0, 0); camera.updateMatrixWorld();
  Object.assign(viewport, {
    camera, scene: new THREE.Scene(), mesh: new THREE.Mesh(original),
    renderer: { render() {}, domElement: {
      style: {}, clientHeight: 800, getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 800 }),
      setPointerCapture: (pointerId: number) => captured.add(pointerId),
      hasPointerCapture: (pointerId: number) => captured.has(pointerId),
      releasePointerCapture: (pointerId: number) => captured.delete(pointerId),
    } },
    controls: { enabled: true }, editingEnabled: true,
    bodyResizeTarget: { partId: "one", solidIndices: [0], minimum: [0, 0, 0], maximum: [10, 20, 30], size: [10, 20, 30] },
    bodyResizeGroup: new THREE.Group(), bodyResizeVertices: new Set([0, 1, 2]),
    bodyResizeOriginal: null, bodyResizePreview: null, bodyResizeLabel: null, bodyResizeDrag: null,
    events: { onBodyResizeCommit: (resize: unknown) => commits.push(resize), onBodyResizePreview: (size: unknown) => previews.push(size), onSelectFace() {} },
    pickBodyResizeHandle: () => ({ corner: [1, 1, 1], axis: 0 }),
    pickFace: () => null, render() {},
  });
  return { viewport, original, captured, commits, previews };
}

function pointer(overrides = {}) {
  return { pointerId: 1, button: 0, clientX: 300, clientY: 300, shiftKey: false, preventDefault() {}, stopPropagation() {}, ...overrides };
}

test("resize Preview uses a copy, keeps other body vertices, and cancellation restores the original", () => {
  const { viewport, original } = fixture();
  viewport.previewBodyResize({ corner: [1, 1, 1], axis: 0 }, [20, 20, 30]);
  assert.notEqual(viewport.mesh.geometry, original);
  assert.equal(viewport.mesh.geometry.getAttribute("position").getX(1), 20);
  assert.equal(viewport.mesh.geometry.getAttribute("position").getX(3), 100);
  assert.equal(original.getAttribute("position").getX(1), 10);
  viewport.cancelBodyResizePreview();
  assert.equal(viewport.mesh.geometry, original);
  assert.equal(viewport.bodyResizeLabel, null);
});

test("dragging sends no document edits before pointerup and commits exactly once", () => {
  const { viewport, captured, commits } = fixture();
  viewport.onPointerDown(pointer());
  assert.equal(viewport.controls.enabled, false);
  assert.ok(captured.has(1));
  viewport.onPointerMove(pointer({ clientX: 350 }));
  assert.equal(commits.length, 0);
  viewport.onPointerUp(pointer({ clientX: 350 }));
  assert.equal(commits.length, 1);
  assert.equal(viewport.controls.enabled, true);
  assert.equal(captured.size, 0);
});

test("click without movement creates no undo entry", () => {
  const { viewport, commits } = fixture();
  viewport.onPointerDown(pointer()); viewport.onPointerUp(pointer());
  assert.equal(commits.length, 0);
});

test("numeric entry during resize commits exact size once and is not overwritten by mouse movement", () => {
  const { viewport, commits } = fixture();
  viewport.onPointerDown(pointer());
  const key = (value: string) => viewport.handleModelingKey({ key: value });
  key("2"); key("5");
  viewport.onPointerMove(pointer({ clientX: 800 }));
  assert.equal(viewport.bodyResizeDrag.size[0], 25);
  key("Enter");
  assert.equal(commits.length, 1);
  assert.deepEqual((commits[0] as any).size, [25, 20, 30]);
});

test("transient exact Preview leaves the committed geometry intact and restores it", () => {
  const { viewport, original } = fixture();
  viewport.setOperationPreview({ positions: [0, 0, 0, 1, 0, 0, 0, 1, 0], indices: [0, 1, 2], face_ranges: [] });
  assert.equal(viewport.mesh.geometry, original);
  assert.equal(viewport.mesh.visible, false);
  assert.ok(viewport.operationPreview);
  viewport.setOperationPreview(null);
  assert.equal(viewport.mesh.visible, true);
  assert.equal(viewport.operationPreview, null);
});

test("clicking a dimension does not deselect its owning body before double click", () => {
  const { viewport } = fixture();
  let selections = 0;
  viewport.events.onSelectFace = () => { selections += 1; };
  viewport.dimGroup = new THREE.Group(); viewport.dimensionEdit = () => {};
  viewport.updatePointer = () => {};
  viewport.raycaster = { intersectObject: () => [{ object: { userData: { dimensionAxis: 1 } } }] };
  viewport.onClick(pointer());
  assert.equal(selections, 0);
  assert.equal(viewport.pickDimension(pointer()), 1);
});

test("designer gesture captures one pointer, previews locally, and cancellation cannot finish twice", () => {
  const { viewport, captured } = fixture();
  const calls: string[] = [];
  viewport.updatePointer = () => {};
  viewport.raycaster = { intersectObject: () => [{ point: new THREE.Vector3(1, 2, 3) }], ray: { intersectPlane: () => new THREE.Vector3(2, 3, 4) } };
  viewport.setDesignerTool({ kind: "sculpt", start: () => calls.push("start"), move: () => calls.push("move"), finish: (cancelled: boolean) => calls.push(cancelled ? "cancel" : "finish") });
  viewport.onPointerDown(pointer());
  viewport.onPointerDown(pointer({ pointerId: 2 }));
  viewport.onPointerMove(pointer({ pointerId: 2 }));
  viewport.onPointerMove(pointer());
  viewport.onPointerCancel(pointer());
  viewport.onPointerCancel(pointer());
  assert.deepEqual(calls, ["start", "move", "cancel"]);
  assert.equal(captured.size, 0);
  assert.equal(viewport.controls.enabled, true);
});

test("a second pointer cannot replace or commit another pointer's resize", () => {
  const { viewport, captured, commits } = fixture();
  viewport.onPointerDown(pointer());
  viewport.onPointerDown(pointer({ pointerId: 2 }));
  viewport.onPointerMove(pointer({ pointerId: 2, clientX: 400 }));
  viewport.onPointerUp(pointer({ pointerId: 2, clientX: 400 }));
  assert.equal(viewport.bodyResizeDrag.pointerId, 1);
  assert.deepEqual([...captured], [1]);
  assert.equal(commits.length, 0);
  viewport.onPointerMove(pointer({ clientX: 350 })); viewport.onPointerUp(pointer({ clientX: 350 }));
  assert.equal(commits.length, 1);
  assert.equal(captured.size, 0);
});

test("pointercancel and lost capture discard the Preview; late pointerup cannot commit it", () => {
  const { viewport, original, captured, commits } = fixture();
  viewport.onPointerDown(pointer()); viewport.onPointerMove(pointer({ clientX: 350 }));
  viewport.onPointerCancel(pointer()); viewport.onPointerUp(pointer({ clientX: 350 }));
  assert.equal(commits.length, 0);
  assert.equal(viewport.mesh.geometry, original);
  assert.equal(captured.size, 0);
  assert.equal(viewport.controls.enabled, true);
});

test("What-mode or geometry busy blocks starting a resize and cancels an in-flight drag", () => {
  const { viewport, commits, captured } = fixture();
  viewport.onPointerDown(pointer()); viewport.onPointerMove(pointer({ clientX: 350 }));
  viewport.setEditingEnabled(false);
  assert.equal(captured.size, 0);
  assert.equal(viewport.controls.enabled, true);
  viewport.onPointerUp(pointer()); viewport.onPointerDown(pointer());
  assert.equal(viewport.bodyResizeDrag, null);
  assert.equal(commits.length, 0);
});

test("changing selection or leaving the tool discards Preview and releases capture", () => {
  const { viewport, original, captured, commits } = fixture();
  viewport.onPointerDown(pointer()); viewport.onPointerMove(pointer({ clientX: 350 }));
  viewport.setBodyResizeHandle(null);
  assert.equal(viewport.bodyResizeTarget, null);
  assert.equal(viewport.mesh.geometry, original);
  assert.equal(captured.size, 0);
  assert.equal(commits.length, 0);
});
