import { clockTime } from '@/lib/lead/format';

// A service's figures over the last day, for the day chart (DEC-1343). Pure. Each point is what the service could
// take when it reported, or how far over it was; never a used count. The chart breaks where the capacity was
// unknown: a figure counts only for the stale limit after its report, and nothing is drawn past that until the
// next report.

export type HistoryPoint = {
  /** ISO instant of the report. */
  at: string;
  available: number | null;
  overBy: number | null;
  status: string;
};

export type History = {
  unitLabel: string;
  established: number;
  since: string;
  until: string;
  staleAfterSeconds: number;
  points: HistoryPoint[];
};

export class HistoryParseError extends Error {
  constructor() {
    super('The history is not in the shape the chart knows.');
    this.name = 'HistoryParseError';
  }
}

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const whole = (value: unknown): number => {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) throw new HistoryParseError();
  return value;
};
const nullableWhole = (value: unknown): number | null => (value === null || value === undefined ? null : whole(value));
const instant = (value: unknown): string => {
  if (typeof value !== 'string' || Number.isNaN(Date.parse(value))) throw new HistoryParseError();
  return value;
};

export function parseHistory(value: unknown): History {
  if (!isObject(value) || !Array.isArray(value.points) || typeof value.unitLabel !== 'string') throw new HistoryParseError();
  return {
    unitLabel: value.unitLabel,
    established: whole(value.established),
    since: instant(value.since),
    until: instant(value.until),
    staleAfterSeconds: whole(value.staleAfterSeconds),
    points: value.points.map((point) => {
      if (!isObject(point) || typeof point.status !== 'string') throw new HistoryParseError();
      return { at: instant(point.at), available: nullableWhole(point.available), overBy: nullableWhole(point.overBy), status: point.status };
    }),
  };
}

/** A stretch of the day on which the figure is known: it holds from `from` to `to`. */
export type KnownStretch = { from: number; to: number; available: number | null; overBy: number | null };
/** A stretch of the day on which the capacity was unknown. */
export type UnknownStretch = { from: number; to: number };

export type Stretches = { known: KnownStretch[]; unknown: UnknownStretch[] };

/** The known and unknown stretches of the day, in epoch ms, from the first moment shown to the last. */
export function stretchesOf(history: History): Stretches {
  const since = Date.parse(history.since);
  const until = Date.parse(history.until);
  const limit = history.staleAfterSeconds * 1000;
  const points = history.points
    .map((point) => ({ ...point, time: Date.parse(point.at) }))
    .filter((point) => point.time <= until)
    .sort((a, b) => a.time - b.time);
  const known: KnownStretch[] = [];
  const unknown: UnknownStretch[] = [];
  let cursor = since;
  for (let i = 0; i < points.length; i += 1) {
    const point = points[i];
    const start = Math.max(point.time, since);
    if (start > cursor) unknown.push({ from: cursor, to: start });
    const next = i + 1 < points.length ? points[i + 1].time : until;
    const holdsTo = Math.min(next, point.time + limit, until);
    if (holdsTo > start) known.push({ from: start, to: holdsTo, available: point.available, overBy: point.overBy });
    cursor = Math.max(start, holdsTo);
    if (cursor < next && next > cursor) {
      unknown.push({ from: cursor, to: next });
      cursor = next;
    }
  }
  if (cursor < until) unknown.push({ from: cursor, to: until });
  return { known, unknown };
}

/** The chart's words for a screen reader: how many reports, and where the capacity was unknown. */
export function chartSummary(history: History): string {
  const { unknown } = stretchesOf(history);
  const reports = history.points.length;
  const head = reports === 0 ? 'No report in the last day.' : `${reports} ${reports === 1 ? 'report' : 'reports'} in the last day.`;
  const gaps = unknown
    .filter((gap) => gap.to - gap.from >= 60_000)
    .map((gap) => `${clockTime(new Date(gap.from).toISOString())} to ${clockTime(new Date(gap.to).toISOString())}`);
  return gaps.length === 0 ? head : `${head} Capacity unknown ${gaps.join(', ')}.`;
}
