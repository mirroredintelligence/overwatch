import { describe, expect, it } from 'vitest';
import { chartSummary, HistoryParseError, parseHistory, stretchesOf, type History } from './history';

// The day chart's maths (DEC-1343): a figure counts only for the stale limit after its report, and the chart breaks
// where the capacity was unknown.

const HOUR = 3_600_000;
const SINCE = Date.parse('2026-11-05T14:00:00Z');
const UNTIL = Date.parse('2026-11-06T14:00:00Z');

function history(points: Array<{ at: string; available?: number | null; overBy?: number | null }>): History {
  return {
    unitLabel: 'beds free',
    established: 10,
    since: new Date(SINCE).toISOString(),
    until: new Date(UNTIL).toISOString(),
    staleAfterSeconds: 7200,
    points: points.map((point) => ({ at: point.at, available: point.available ?? 4, overBy: point.overBy ?? null, status: 'accepting' })),
  };
}

const at = (hoursAfterSince: number) => new Date(SINCE + hoursAfterSince * HOUR).toISOString();

describe('stretchesOf', () => {
  it('has nothing known and the whole day unknown when there is no report', () => {
    expect(stretchesOf(history([]))).toEqual({ known: [], unknown: [{ from: SINCE, to: UNTIL }] });
  });

  it('holds a figure for the stale limit and then breaks until the next report', () => {
    const { known, unknown } = stretchesOf(history([{ at: at(2) }, { at: at(10), available: 6 }]));
    expect(known[0]).toMatchObject({ from: SINCE + 2 * HOUR, to: SINCE + 4 * HOUR, available: 4 });
    expect(known[1]).toMatchObject({ from: SINCE + 10 * HOUR, to: SINCE + 12 * HOUR, available: 6 });
    expect(unknown).toEqual([
      { from: SINCE, to: SINCE + 2 * HOUR },
      { from: SINCE + 4 * HOUR, to: SINCE + 10 * HOUR },
      { from: SINCE + 12 * HOUR, to: UNTIL },
    ]);
  });

  it('joins two reports that are closer than the stale limit with no gap between them', () => {
    const { known, unknown } = stretchesOf(history([{ at: at(2) }, { at: at(3), available: 7 }]));
    expect(known[0]).toMatchObject({ from: SINCE + 2 * HOUR, to: SINCE + 3 * HOUR });
    expect(known[1]).toMatchObject({ from: SINCE + 3 * HOUR, to: SINCE + 5 * HOUR });
    expect(unknown.some((gap) => gap.from < SINCE + 5 * HOUR && gap.to > SINCE + 2 * HOUR)).toBe(false);
  });

  it('never draws past the end of the day', () => {
    const { known } = stretchesOf(history([{ at: new Date(UNTIL - HOUR).toISOString() }]));
    expect(known[0].to).toBe(UNTIL);
  });
});

describe('chartSummary', () => {
  it('says how many reports and where the capacity was unknown, in words', () => {
    const summary = chartSummary(history([{ at: at(2) }]));
    expect(summary).toContain('1 report in the last day.');
    expect(summary).toContain('Capacity unknown');
  });

  it('says there was no report', () => {
    expect(chartSummary(history([]))).toContain('No report in the last day.');
  });
});

describe('parseHistory', () => {
  it('reads the back end answer and refuses a malformed one', () => {
    const body = {
      unitLabel: 'beds free',
      established: 10,
      since: '2026-11-05T14:00:00Z',
      until: '2026-11-06T14:00:00Z',
      staleAfterSeconds: 7200,
      points: [{ at: '2026-11-06T09:00:00Z', available: 4, overBy: null, status: 'accepting' }],
    };
    expect(parseHistory(body).points).toHaveLength(1);
    expect(() => parseHistory({ ...body, points: 'no' })).toThrow(HistoryParseError);
    expect(() => parseHistory({ ...body, since: 'not a time' })).toThrow(HistoryParseError);
    expect(() => parseHistory({ ...body, points: [{ at: 'x', available: 1, overBy: null, status: 'a' }] })).toThrow(HistoryParseError);
  });
});
