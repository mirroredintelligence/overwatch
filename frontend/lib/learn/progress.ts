// Stub (red commit): every lesson reads as done, so the guard tests fail on their assertions.
export function getDone(): Set<string> {
  return new Set(['stub']);
}
export function markDone(id: string): void {
  void id;
}
