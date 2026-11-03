import { readFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { findHelpAnswers } from "../app/ui/src/helpSearch.ts";
import { decodeMeshBinary, mapMeshPositionsForViewport } from "../app/ui/src/meshBinary.ts";
import type { CommandDef, HelpIndex } from "../app/ui/src/types.ts";

function argument(name: string, fallback: number): number {
  const index = process.argv.indexOf(name);
  if (index < 0) return fallback;
  const value = Number(process.argv[index + 1]);
  if (!Number.isInteger(value) || value <= 0) throw new Error(`${name} должен быть положительным integer`);
  return value;
}

function percentile(values: number[], fraction: number): number {
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.max(0, Math.ceil(sorted.length * fraction) - 1);
  return sorted[index];
}

function syntheticMesh(triangleCount: number): ArrayBuffer {
  const vertexCount = triangleCount * 3;
  const positionCount = vertexCount * 3;
  const buffer = new ArrayBuffer(8 + positionCount * 4 + triangleCount * 3 * 4);
  const view = new DataView(buffer);
  view.setUint32(0, vertexCount, true);
  view.setUint32(4, triangleCount, true);
  for (let index = 0; index < positionCount; index += 1) {
    view.setFloat32(8 + index * 4, (index % 97) / 10, true);
  }
  const indexOffset = 8 + positionCount * 4;
  for (let index = 0; index < triangleCount * 3; index += 1) {
    view.setUint32(indexOffset + index * 4, index, true);
  }
  return buffer;
}

async function main(): Promise<void> {
  const triangleCount = argument("--triangles", 200_000);
  const runs = argument("--runs", 7);
  const root = new URL("../", import.meta.url);
  const [helpRaw, commandsRaw] = await Promise.all([
    readFile(new URL("app/ui/public/help/index.json", root), "utf8"),
    readFile(new URL("app/shared/commands.json", root), "utf8"),
  ]);
  const help = JSON.parse(helpRaw) as HelpIndex;
  const commands = (JSON.parse(commandsRaw) as { commands: CommandDef[] }).commands;
  const queries = [
    "Как сделать изгиб фланца?",
    "Как экспортировать STL?",
    "Как отменить вычисление?",
    "Как измерить диаметр?",
  ];
  findHelpAnswers(help, queries[0], commands);
  const helpDurations: number[] = [];
  for (let index = 0; index < 1_000; index += 1) {
    const startedAt = performance.now();
    findHelpAnswers(help, queries[index % queries.length], commands);
    helpDurations.push(performance.now() - startedAt);
  }

  const buffer = syntheticMesh(triangleCount);
  const decodeDurations: number[] = [];
  const mapDurations: number[] = [];
  let mapped: Float32Array | null = null;
  for (let index = 0; index < runs; index += 1) {
    globalThis.gc?.();
    const decodeStartedAt = performance.now();
    const mesh = decodeMeshBinary(buffer);
    decodeDurations.push(performance.now() - decodeStartedAt);
    const mapStartedAt = performance.now();
    mapped = mapMeshPositionsForViewport(mesh.positions);
    mapDurations.push(performance.now() - mapStartedAt);
  }
  if (mapped === null || mapped.length !== triangleCount * 9) {
    throw new Error("Synthetic viewport workload декодирован некорректно");
  }

  const memory = process.memoryUsage();
  process.stdout.write(JSON.stringify({
    triangle_count: triangleCount,
    vertex_count: triangleCount * 3,
    binary_bytes: buffer.byteLength,
    help_search_ms: {
      samples: helpDurations.length,
      p50: percentile(helpDurations, 0.5),
      p95: percentile(helpDurations, 0.95),
      max: Math.max(...helpDurations),
    },
    binary_decode_ms: {
      samples: decodeDurations.length,
      p50: percentile(decodeDurations, 0.5),
      p95: percentile(decodeDurations, 0.95),
      max: Math.max(...decodeDurations),
    },
    viewport_position_map_ms: {
      samples: mapDurations.length,
      p50: percentile(mapDurations, 0.5),
      p95: percentile(mapDurations, 0.95),
      max: Math.max(...mapDurations),
    },
    process_memory_bytes: {
      rss: memory.rss,
      heap_used: memory.heapUsed,
      array_buffers: memory.arrayBuffers,
    },
  }));
}

await main();
