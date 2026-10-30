// Stub (W41 red).
export type Figure = { value: number | null; suppressed: boolean };
export type WeekSummary = {
  from: string; to: string;
  referrals: Figure; bestFitUnavailablePct: Figure; onTimePct: Figure; medianMinutesToConfirmed: Figure;
  updates: Figure; minutesPerCall: number | null;
};
export function weekEndingDefault(now: Date): string { void now; throw new Error('not implemented'); }
export function weekStartFor(ending: string): string { void ending; throw new Error('not implemented'); }
export function summaryFromParameters(body: unknown, minutesPerCall?: number | null): WeekSummary {
  void body; void minutesPerCall; throw new Error('not implemented');
}
export function timeBack(updates: Figure, minutesPerCall: number | null): { sentence: string; estimate: string | null } {
  void updates; void minutesPerCall; throw new Error('not implemented');
}
