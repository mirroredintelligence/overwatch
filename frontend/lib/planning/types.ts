// The planning view's data (W51). Aggregates from the decision log. A count under 10 arrives as
// suppressed: true with no number, and is shown as "fewer than 10".

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

export type Planning = {
  cohort: string;
  referrals: number;
  bestFitUnavailable: { count: number; pct: number };
  wentElsewhere: number;
  flows: Flow[];
  /** Seven days (Monday first) by four bands of six hours. */
  grid: number[][];
  declinedDespite: Declined[];
};
