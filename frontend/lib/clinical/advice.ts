// Stub (W44 red).
export const ADVICE_CHOICES = [] as const;
export const NOTE_LIMIT = 280;
export function validateAdvice(input: unknown): { ok: true; value: unknown } | { ok: false; errors: string[] } {
  void input; throw new Error('not implemented');
}
