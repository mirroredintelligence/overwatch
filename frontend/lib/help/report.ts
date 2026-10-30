// Stub (W46 red).
export const SAFETY_CATEGORIES = [] as const;
export const PROBLEM_KINDS = [] as const;
export const REPORT_LIMIT = 280;
export function checkSafetyConcern(input: unknown): { ok: true; value: unknown } | { ok: false; errors: string[] } {
  void input; throw new Error('not implemented');
}
export function checkProblem(input: unknown): { ok: true; value: unknown } | { ok: false; errors: string[] } {
  void input; throw new Error('not implemented');
}
export function supportSharingOn(): boolean { throw new Error('not implemented'); }
