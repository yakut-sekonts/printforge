import type { FaceRange, MeshData } from "./types";

const HEADER_BYTES = 8;
const COMPONENTS_PER_TRIANGLE = 3;
const BYTES_PER_COMPONENT = 4;
const HOST_IS_LITTLE_ENDIAN = new Uint8Array(new Uint32Array([0x01020304]).buffer)[0] === 4;

function checkedComponentCount(count: number, label: string): number {
  const components = count * COMPONENTS_PER_TRIANGLE;
  if (!Number.isSafeInteger(components)) {
    throw new Error(`Некорректное число ${label} в ресурсе сетки`);
  }
  return components;
}

function portableFloat32(data: DataView, byteOffset: number, count: number): Float32Array {
  const values = new Float32Array(count);
  for (let index = 0; index < count; index += 1) {
    values[index] = data.getFloat32(byteOffset + index * BYTES_PER_COMPONENT, true);
  }
  return values;
}

function portableUint32(data: DataView, byteOffset: number, count: number): Uint32Array {
  const values = new Uint32Array(count);
  for (let index = 0; index < count; index += 1) {
    values[index] = data.getUint32(byteOffset + index * BYTES_PER_COMPONENT, true);
  }
  return values;
}

export function decodeMeshBinary(buffer: ArrayBuffer, faceRanges: FaceRange[] = []): MeshData {
  if (buffer.byteLength < HEADER_BYTES) {
    throw new Error("Ресурс сетки короче обязательного заголовка");
  }
  const view = new DataView(buffer);
  const vertexCount = view.getUint32(0, true);
  const triangleCount = view.getUint32(4, true);
  const positionCount = checkedComponentCount(vertexCount, "вершин");
  const indexCount = checkedComponentCount(triangleCount, "треугольников");
  const positionBytes = positionCount * BYTES_PER_COMPONENT;
  const expectedBytes = HEADER_BYTES + positionBytes + indexCount * BYTES_PER_COMPONENT;
  if (!Number.isSafeInteger(expectedBytes) || buffer.byteLength !== expectedBytes) {
    throw new Error(
      `Длина ресурса сетки не совпадает с заголовком: ${buffer.byteLength} вместо ${expectedBytes}`,
    );
  }

  const indexOffset = HEADER_BYTES + positionBytes;
  const positions = HOST_IS_LITTLE_ENDIAN
    ? new Float32Array(buffer, HEADER_BYTES, positionCount)
    : portableFloat32(view, HEADER_BYTES, positionCount);
  const indices = HOST_IS_LITTLE_ENDIAN
    ? new Uint32Array(buffer, indexOffset, indexCount)
    : portableUint32(view, indexOffset, indexCount);
  return {
    vertex_count: vertexCount,
    triangle_count: triangleCount,
    positions,
    indices,
    face_ranges: faceRanges,
  };
}

export function mapMeshPositionsForViewport(positions: ArrayLike<number>): Float32Array {
  if (positions.length % 3 !== 0) {
    throw new Error("Массив позиций сетки должен содержать полные XYZ-тройки");
  }
  const mapped = new Float32Array(positions.length);
  for (let index = 0; index < positions.length; index += 3) {
    mapped[index] = positions[index];
    mapped[index + 1] = positions[index + 2];
    mapped[index + 2] = -positions[index + 1];
  }
  return mapped;
}
