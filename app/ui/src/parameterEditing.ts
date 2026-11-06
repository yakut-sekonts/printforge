import type { DocState, TemplateDef, TemplateParam } from "./types";

export function validateParameterValue(value: number, parameter: TemplateParam | undefined): void {
  if (!Number.isFinite(value)) throw new Error("Значение должно быть конечным числом");
  if (parameter?.min != null) {
    if (value < parameter.min) throw new Error(`Минимальное значение: ${parameter.min} ${parameter.unit}`);
  } else if (value <= 0) {
    throw new Error("Значение должно быть больше нуля");
  }
}

export function parameterValues(doc: DocState, template: TemplateDef | null, partId?: string): Record<string, number> {
  const part = partId ? doc.parts?.find((candidate) => candidate.part_id === partId) : doc.parts?.[0];
  const first = !part || part.part_id === doc.parts?.[0]?.part_id;
  return {
    ...Object.fromEntries((template?.params ?? []).map((parameter) => [parameter.name, parameter.default])),
    ...(first ? doc.params : {}),
    ...part?.params,
  };
}

export function parameterText(doc: DocState, partId: string | undefined, name: string, value: number): string {
  const expression = partId ? doc.expressions[`${partId}.${name}`] : undefined;
  if (expression != null) return expression;
  const first = !partId || partId === doc.parts?.[0]?.part_id;
  return first && doc.expressions[name] != null ? doc.expressions[name] : String(value);
}

export function reconcileParameterDrafts(
  values: Record<string, string>, previous: Record<string, string>, next: Record<string, string>,
): Record<string, string> {
  return Object.fromEntries(Object.entries(next).map(([name, committed]) => [
    name,
    previous[name] === committed && values[name] != null && values[name] !== previous[name]
      ? values[name] : committed,
  ]));
}
