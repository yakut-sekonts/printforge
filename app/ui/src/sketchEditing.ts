import type { ConstrainedSketch, ConstrainedSketchEntity, Point2, SketchConstraint, SketchPointRef } from "./types";

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

export function setSketchDimension(sketch: ConstrainedSketch, entity: string, kind: "length" | "radius", value: number): ConstrainedSketch {
  if (!Number.isFinite(value) || value <= 0) throw new Error("Размер должен быть больше нуля.");
  let found = false;
  let changed = false;
  const constraints = sketch.constraints.map((constraint) => {
    if (constraint.type !== "dimension" || !("entity" in constraint) || constraint.entity !== entity || constraint.kind !== kind) return constraint;
    found = true;
    if (constraint.value === value) return constraint;
    changed = true;
    return { ...constraint, value };
  });
  if (!found) constraints.push({ type: "dimension", entity, kind, value });
  return found && !changed ? sketch : { ...sketch, constraints };
}

export function sketchForRadiusDrag(sketch: ConstrainedSketch, entity: string, radius: number): ConstrainedSketch {
  const hasRadius = sketch.constraints.some((constraint) => constraint.type === "dimension" && "entity" in constraint && constraint.kind === "radius" && constraint.entity === entity);
  return hasRadius ? setSketchDimension(sketch, entity, "radius", radius) : sketch;
}

export function sketchDimensionValue(sketch: ConstrainedSketch, entity: ConstrainedSketchEntity): number | null {
  if (entity.type === "arc") return null;
  const kind = entity.type === "circle" ? "radius" : "length";
  const constraint = sketch.constraints.find((item) => item.type === "dimension" && "entity" in item && item.entity === entity.id && item.kind === kind);
  if (constraint?.type === "dimension") return constraint.value;
  const value = entity.type === "circle" ? entity.radius : Math.hypot(entity.end[0] - entity.start[0], entity.end[1] - entity.start[1]);
  return Math.round(value * 100) / 100;
}

export function sketchPairActions(first: ConstrainedSketchEntity | undefined, second: ConstrainedSketchEntity | undefined) {
  const lines = first?.type === "line" && second?.type === "line";
  const circles = first?.type === "circle" && second?.type === "circle";
  return { equal: lines || circles, directional: lines };
}

export function describeSketchConstraint(constraint: SketchConstraint): string {
  switch (constraint.type) {
    case "coincident": return `Совпадение точек · ${constraint.a[0]} / ${constraint.b[0]}`;
    case "horizontal": return `Горизонтально · ${constraint.entity}`;
    case "vertical": return `Вертикально · ${constraint.entity}`;
    case "parallel": return `Параллельно · ${constraint.a} / ${constraint.b}`;
    case "perpendicular": return `Перпендикулярно · ${constraint.a} / ${constraint.b}`;
    case "equal": return `Равные размеры · ${constraint.a} / ${constraint.b}`;
    case "tangent": return `Касание · ${constraint.line} / ${constraint.circle}`;
    case "fix": return `Закреплено · ${"entity" in constraint ? constraint.entity : constraint.point[0]}`;
    case "dimension": {
      const name = { radius: "Радиус", length: "Длина", distance: "Расстояние", distance_x: "Расстояние по U", distance_y: "Расстояние по V" }[constraint.kind];
      const target = "entity" in constraint ? constraint.entity : `${constraint.a[0]} / ${constraint.b[0]}`;
      return `${name} · ${target} · ${constraint.value} мм`;
    }
  }
}

export function pointsAfterToolChange(points: Point2[], contourInProgress: boolean): Point2[] {
  return contourInProgress ? points.slice(0, 1) : [];
}

export function checkpointSketchContour(sketch: ConstrainedSketch, undo: ConstrainedSketch[]) {
  return { sketch, undo: [...undo] };
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
