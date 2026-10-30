// Stub (red commit).
export type FunnelStep = {
  name: string;
  pct: number | null;
  count: number | null;
  suppressed: boolean;
  exitElementId?: string;
  medianSeconds?: number;
};

export type BiggestDrop = {
  from: string;
  to: string;
  points: number;
  exitElementId?: string;
  medianSeconds?: number;
};

export function biggestDrop(steps: readonly FunnelStep[]): BiggestDrop | null {
  void steps;
  return null;
}
