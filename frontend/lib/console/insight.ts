import type { FunnelStep } from './funnel';

// Shapes of the insight page's data (W49). Aggregates only: nothing here names a person, and a
// group under 10 arrives with suppressed set and no figure.

export const RANGES = [
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
] as const;
export type Range = (typeof RANGES)[number]['value'];

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

export type FrictionRow = {
  elementId: string;
  kind: string;
  events: number;
  interactions: number;
  rate: number;
};

export type Vital = { measure: string; p75: number; budget: number; unit: 'ms' | 's' | 'score' };
export type Slow = { name: string; p95Ms: number };
export type Compare = { old: string; new: string };
export type Measure = { measure: string; old: number; new: number; unit: 'ms' | 'count' };
export type PipelineRow = { name: string; active: number; deadLettered: number; oldestSeconds: number | null };
export type PathRow = { route: string; sessions: number | null; medianSeconds: number | null; suppressed: boolean };
