export function geometryProgressLabel(elapsedSeconds: number, cancelling: boolean): string {
  if (cancelling) return "Останавливаем вычисление…";
  const elapsed = Math.max(0, Math.floor(elapsedSeconds));
  return `Вычисление${elapsed > 0 ? ` · ${elapsed} с` : ""}…`;
}
