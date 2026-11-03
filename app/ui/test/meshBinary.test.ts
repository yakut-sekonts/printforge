import assert from "node:assert/strict";
import test from "node:test";
import { decodeMeshBinary, mapMeshPositionsForViewport } from "../src/meshBinary.ts";

function encodeMesh(positions: number[], indices: number[]): ArrayBuffer {
  const buffer = new ArrayBuffer(8 + positions.length * 4 + indices.length * 4);
  const view = new DataView(buffer);
  view.setUint32(0, positions.length / 3, true);
  view.setUint32(4, indices.length / 3, true);
  positions.forEach((value, index) => view.setFloat32(8 + index * 4, value, true));
  const indexOffset = 8 + positions.length * 4;
  indices.forEach((value, index) => view.setUint32(indexOffset + index * 4, value, true));
  return buffer;
}

test("декодирует little-endian mesh без JSON-массивов и лишней копии", () => {
  const buffer = encodeMesh([0, 0, 0, 1.5, 0, 0, 0, 2.5, 0], [0, 1, 2]);
  const faceRanges = [{ face_index: 7, tri_start: 0, tri_count: 1 }];
  const mesh = decodeMeshBinary(buffer, faceRanges);

  assert.equal(mesh.vertex_count, 3);
  assert.equal(mesh.triangle_count, 1);
  assert.ok(mesh.positions instanceof Float32Array);
  assert.ok(mesh.indices instanceof Uint32Array);
  assert.equal(mesh.positions.buffer, buffer);
  assert.equal(mesh.indices.buffer, buffer);
  assert.deepEqual(Array.from(mesh.positions), [0, 0, 0, 1.5, 0, 0, 0, 2.5, 0]);
  assert.deepEqual(Array.from(mesh.indices), [0, 1, 2]);
  assert.equal(mesh.face_ranges, faceRanges);
});

test("отклоняет усечённый, расширенный и слишком короткий ресурс", () => {
  const valid = encodeMesh([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2]);
  assert.throws(() => decodeMeshBinary(valid.slice(0, valid.byteLength - 1)), /не совпадает/);

  const extended = new Uint8Array(valid.byteLength + 1);
  extended.set(new Uint8Array(valid));
  assert.throws(() => decodeMeshBinary(extended.buffer), /не совпадает/);
  assert.throws(() => decodeMeshBinary(new ArrayBuffer(7)), /заголовка/);
});

test("преобразует CAD XYZ в viewport XZ−Y", () => {
  assert.deepEqual(
    Array.from(mapMeshPositionsForViewport(new Float32Array([1, 2, 3, -4, -5, -6]))),
    [1, 3, -2, -4, -6, 5],
  );
  assert.throws(() => mapMeshPositionsForViewport([1, 2]), /XYZ-тройки/);
});
