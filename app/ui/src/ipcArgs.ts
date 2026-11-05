export function nativeIpcArgs(args?: Record<string, unknown>): Record<string, unknown> | undefined {
  if (args == null) return undefined;
  return Object.fromEntries(Object.entries(args).map(([key, value]) => [
    key.replace(/_([a-z])/g, (_match, letter: string) => letter.toUpperCase()),
    value,
  ]));
}
