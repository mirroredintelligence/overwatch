// Funnel arithmetic for the insight page (W49). A suppressed step (a group under 10) has no
// percentage, so it is skipped: it is never named as either side of a drop.

export type FunnelStep = {
  name: string;
  pct: number | null;
  count: number | null;
  suppressed: boolean;
  /** The element the people in this step left from, when the API names one. */
  exitElementId?: string;
  /** The median time from this step to the next, in seconds. */
  medianSeconds?: number;
};

export type BiggestDrop = {
  from: string;
  to: string;
  points: number;
  exitElementId?: string;
  medianSeconds?: number;
};

/** The largest fall in percentage points between two shown steps, or null when none falls. */
export function biggestDrop(steps: readonly FunnelStep[]): BiggestDrop | null {
  const shown = steps.filter((step): step is FunnelStep & { pct: number } => !step.suppressed && step.pct !== null);
  let best: BiggestDrop | null = null;
  for (let index = 1; index < shown.length; index += 1) {
    const before = shown[index - 1];
    const after = shown[index];
    if (before === undefined || after === undefined) continue;
    const points = before.pct - after.pct;
    if (points > 0 && (best === null || points > best.points)) {
      best = {
        from: before.name,
        to: after.name,
        points,
        ...(before.exitElementId !== undefined ? { exitElementId: before.exitElementId } : {}),
        ...(before.medianSeconds !== undefined ? { medianSeconds: before.medianSeconds } : {}),
      };
    }
  }
  return best;
}
