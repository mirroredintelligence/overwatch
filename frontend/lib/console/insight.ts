import type { FunnelStep } from './funnel';

// Shapes of the insight page's data (W49, W9F): the answers of the back end's `GET /support/insight/{tab}`
// (routes_insight.py; the samples in test/fixtures/insight-shapes.ts are made by its own mappers).
// Aggregates only: nothing here names a person, and a group under 10 arrives with suppressed set and no
// figure. The counters are daily, so "24 hours" is yesterday and today.

export const RANGES = [
  { value: '24h', label: 'Today and yesterday' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
] as const;
export type Range = (typeof RANGES)[number]['value'];

export const DEVICES = [
  { value: 'phone', label: 'Phone' },
  { value: 'tablet', label: 'Tablet' },
  { value: 'desktop', label: 'Desktop' },
] as const;
export type Device = (typeof DEVICES)[number]['value'];

export const TABS = ['funnels', 'paths', 'friction', 'performance', 'releases'] as const;
export type InsightTab = (typeof TABS)[number];

export const TAB_LABELS: Record<InsightTab, string> = {
  funnels: 'Funnels',
  paths: 'Paths',
  friction: 'Friction',
  performance: 'Performance',
  releases: 'Releases',
};

export type Channel = { channel: string; pct: number | null; suppressed: boolean };
export type Funnel = {
  name: string;
  label: string;
  steps: FunnelStep[];
  split: Channel[];
};

/** A control's friction (rate and review flag from the back end), or the page's own (a route, no rate). */
export type FrictionRow = {
  elementId: string;
  kind: string;
  route: string | null;
  events: number;
  interactions: number | null;
  rate: number | null;
  /** The back end's review flag: over 5%, strictly. The page does not work it out again. */
  review: boolean;
};

export type Vital = {
  measure: string;
  metric: 'lcp' | 'inp' | 'cls';
  device: Device;
  p75: number | null;
  budget: number;
  unit: 'ms' | 'score';
  suppressed: boolean;
};
export type Slow = { name: string; p95Ms: number };
export type Compare = { old: string; new: string };
export type Measure = {
  measure: string;
  old: number;
  new: number;
  unit: 'ms' | 'score' | 'percent' | 'count';
  /** Held for review by the release gate: more than 10% slower at p75, or friction 2 points up. */
  review?: boolean;
};
export type PipelineRow = { name: string; active: number; deadLettered: number; oldestSeconds: number | null };
export type PathRow = { route: string; sessions: number | null; medianSeconds: number | null; suppressed: boolean };
