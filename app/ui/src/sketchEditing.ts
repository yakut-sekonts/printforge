import type { ConstrainedSketch, ConstrainedSketchEntity, Point2, SketchPointRef } from "./types";

export function sketchPoints(entity: ConstrainedSketchEntity): Array<{ ref: SketchPointRef; point: Point2 }> {
  return entity.type === "circle" ? [{ ref: [entity.id, "center"], point: entity.center }]
    : [{ ref: [entity.id, "start"], point: entity.start }, { ref: [entity.id, "end"], point: entity.end },
      ...(entity.type === "arc" ? [{ ref: [entity.id, "mid"] as SketchPointRef, point: entity.mid }] : [])];
}

export function snapSketchPoint(sketch: ConstrainedSketch, point: Point2, tolerance: number): { point: Point2; ref?: SketchPointRef } {
  let nearest: { point: Point2; ref?: SketchPointRef } = { point };
  let distance = tolerance;
  for (const entity of sketch.entities) for (const candidate of sketchPoints(entity)) {
    const error = Math.hypot(candidate.point[0] - point[0], candidate.point[1] - point[1]);
    if (error < distance) { nearest = candidate; distance = error; }
  }
  return nearest;
}

export function addSketchEntity(sketch: ConstrainedSketch, entity: ConstrainedSketchEntity, infer = true): ConstrainedSketch {
  if (sketch.entities.some((candidate) => candidate.id === entity.id)) throw new Error("ID элемента уже существует.");
  const constraints = [...sketch.constraints];
  if (entity.type !== "circle") {
    for (const endpoint of ["start", "end"] as const) {
      const nearest = snapSketchPoint(sketch, entity[endpoint], 1e-5);
      if (nearest.ref) constraints.push({ type: "coincident", a: [entity.id, endpoint], b: nearest.ref });
    }
    if (infer && entity.type === "line") {
      const delta = [entity.end[0] - entity.start[0], entity.end[1] - entity.start[1]];
      const length = Math.hypot(...delta);
      if (length < 1e-5) throw new Error("Линия должна иметь ненулевую длину.");
      if (Math.abs(delta[1]) / length < 0.035) constraints.push({ type: "horizontal", entity: entity.id });
      else if (Math.abs(delta[0]) / length < 0.035) constraints.push({ type: "vertical", entity: entity.id });
    }
  } else if (!Number.isFinite(entity.radius) || entity.radius <= 0) throw new Error("Радиус должен быть больше нуля.");
  return { ...sketch, entities: [...sketch.entities, entity], constraints };
}

export function addSketchContour(sketch: ConstrainedSketch, contour: string[] | string, hole: boolean): ConstrainedSketch {
  const regions = (sketch.regions ?? []).map((region) => ({ ...region, holes: [...region.holes] }));
  if (hole) {
    if (!regions.length) throw new Error("Сначала замкните внешний контур, затем добавьте отверстие.");
    regions[regions.length - 1].holes.push(contour);
  } else regions.push({ outer: contour, holes: [] });
  return { ...sketch, regions };
}

export function arcPolyline(entity: Extract<ConstrainedSketchEntity, { type: "arc" }>): Point2[] {
  const [startX, startY] = entity.start, [midX, midY] = entity.mid, [endX, endY] = entity.end;
  const determinant = 2 * (startX * (midY - endY) + midX * (endY - startY) + endX * (startY - midY));
  if (Math.abs(determinant) < 1e-8) return [entity.start, entity.mid, entity.end];
  const startNorm = startX ** 2 + startY ** 2, midNorm = midX ** 2 + midY ** 2, endNorm = endX ** 2 + endY ** 2;
  const centerX = (startNorm * (midY - endY) + midNorm * (endY - startY) + endNorm * (startY - midY)) / determinant;
  const centerY = (startNorm * (endX - midX) + midNorm * (startX - endX) + endNorm * (midX - startX)) / determinant;
  const startAngle = Math.atan2(startY - centerY, startX - centerX);
  const normalize = (angle: number) => (angle + Math.PI * 4) % (Math.PI * 2);
  const endAngle = normalize(Math.atan2(endY - centerY, endX - centerX) - startAngle);
  const midAngle = normalize(Math.atan2(midY - centerY, midX - centerX) - startAngle);
  const sweep = midAngle <= endAngle ? endAngle : endAngle - Math.PI * 2;
  const radius = Math.hypot(startX - centerX, startY - centerY);
  return Array.from({ length: 49 }, (_, index) => {
    const angle = startAngle + sweep * index / 48;
    return [centerX + radius * Math.cos(angle), centerY + radius * Math.sin(angle)];
  });
}
