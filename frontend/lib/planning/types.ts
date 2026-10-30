// The planning view's data (W51, `GET /planning`). Aggregates from the decision log. A count under 10
// arrives as suppressed: true with no number, and is shown as "fewer than 10".

export const PERIODS = [
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
  { value: '12m', label: 'Last 12 months' },
] as const;
export type Period = (typeof PERIODS)[number]['value'];

export const NEEDS = [
  { value: 'all', label: 'All' },
  { value: 'falls-frailty', label: 'Falls and frailty' },
  { value: 'iv-therapy', label: 'IV therapy' },
  { value: 'palliative', label: 'Palliative' },
] as const;
export type Need = (typeof NEEDS)[number]['value'];

export type Flow = {
  bestFit: string;
  state: string;
  wentTo: string;
  count: number | null;
  suppressed: boolean;
};

export type Declined = { service: string; count: number | null; suppressed: boolean };

/** A headline count: null and suppressed when the back end withheld it (under 10). */
export type Count = { count: number | null; suppressed: boolean };

export type Planning = {
  cohort: string;
  referrals: Count;
  /** The share is null when its base is under 10. */
  bestFitUnavailable: Count & { pct: number | null };
  wentElsewhere: Count;
  flows: Flow[];
  /** Seven days (Monday first) by four bands of six hours. A cell under 10 is null: a hidden cell is not a zero. */
  grid: (number | null)[][];
  /** The back end's busiest cell (a day index, a band index and its count, at least 10), or null. */
  busiest: { day: number; band: number; count: number } | null;
  declinedDespite: Declined[];
};
