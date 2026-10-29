import { describe, expect, it } from 'vitest';
import {
  assessBoard,
  MAX_FUTURE_SKEW_MS,
  POLL_INTERVAL_MS,
  STALE_AFTER_MS,
  STREAM_GAP_MS,
  STREAM_RETRY_MS,
  type Health,
} from './liveness';

const T = Date.parse('2026-10-23T13:12:00Z');
const NONE: Health = { streamDownSince: null, failingSince: null, unreadableSince: null };

function assess(over: {
  builtAgo?: number;
  health?: Partial<Health>;
  offset?: number;
  nowLocal?: number;
}) {
  const nowLocal = over.nowLocal ?? T;
  const offset = over.offset ?? 0;
  return assessBoard({
    generatedAt: new Date(nowLocal + offset - (over.builtAgo ?? 0)).toISOString(),
    nowLocal,
    clockOffsetMs: offset,
    health: { ...NONE, ...over.health },
  });
}

describe('the limits (DEC-152)', () => {
  it('polls every 60 s, calls the stream gapped after 10 s, retries a closed stream after 5 s', () => {
    expect(POLL_INTERVAL_MS).toBe(60_000);
    expect(STREAM_GAP_MS).toBe(10_000);
    expect(STREAM_RETRY_MS).toBe(5_000);
  });

  it('calls a board old after 3 minutes: one poll interval, the back end cache lifetime, and one missed poll', () => {
    expect(STALE_AFTER_MS).toBe(180_000);
    expect(STALE_AFTER_MS).toBeGreaterThanOrEqual(2 * POLL_INTERVAL_MS);
    expect(MAX_FUTURE_SKEW_MS).toBe(60_000);
  });
});

describe('assessBoard: live', () => {
  it('is live for a board that was just built, with the stream up', () => {
    expect(assess({})).toEqual({ mode: 'live', streamPaused: false });
  });

  it('stays live up to and including 3 minutes old, and is last known the moment it is older', () => {
    expect(assess({ builtAgo: STALE_AFTER_MS - 1 }).mode).toBe('live');
    expect(assess({ builtAgo: STALE_AFTER_MS }).mode).toBe('live');
    const old = assess({ builtAgo: STALE_AFTER_MS + 1 });
    expect(old).toMatchObject({ mode: 'last-known', reason: 'old', ageMs: STALE_AFTER_MS + 1 });
  });

  it('is only paused, not last known, when the stream has been down for more than 10 s and the board is fresh', () => {
    expect(assess({ health: { streamDownSince: T - STREAM_GAP_MS } })).toEqual({ mode: 'live', streamPaused: false });
    expect(assess({ health: { streamDownSince: T - STREAM_GAP_MS - 1 } })).toEqual({ mode: 'live', streamPaused: true });
  });

  it('a failed refetch with the stream up is not by itself last known (the poll tries again)', () => {
    expect(assess({ health: { failingSince: T - 30_000 } }).mode).toBe('live');
  });
});

describe('assessBoard: last known', () => {
  const gapped = T - STREAM_GAP_MS - 1;

  it('is last known, reason offline, when the stream has been down for more than 10 s and the last refetch failed', () => {
    const result = assess({ health: { streamDownSince: gapped, failingSince: T - 2_000 } });
    expect(result).toMatchObject({ mode: 'last-known', reason: 'offline' });
  });

  it('is not offline at exactly 10 s of stream gap', () => {
    expect(assess({ health: { streamDownSince: T - STREAM_GAP_MS, failingSince: T - 2_000 } }).mode).toBe('live');
  });

  it('says it has been offline since the first failure, not the latest', () => {
    const result = assess({ health: { streamDownSince: gapped, failingSince: T - 8_000 } });
    expect(result).toMatchObject({ since: new Date(T - 8_000).toISOString() });
  });

  it('is last known at once, reason unreadable, for an answer that could not be read, with the stream up', () => {
    const result = assess({ health: { unreadableSince: T - 1_000 } });
    expect(result).toMatchObject({ mode: 'last-known', reason: 'unreadable', since: new Date(T - 1_000).toISOString() });
  });

  it('prefers unreadable over offline over old, and keeps the earliest failure as the since time', () => {
    const all = assess({
      builtAgo: STALE_AFTER_MS + 5_000,
      health: { streamDownSince: gapped, failingSince: T - 9_000, unreadableSince: T - 4_000 },
    });
    expect(all).toMatchObject({ reason: 'unreadable', since: new Date(T - 9_000).toISOString() });

    const noUnreadable = assess({
      builtAgo: STALE_AFTER_MS + 5_000,
      health: { streamDownSince: gapped, failingSince: T - 9_000 },
    });
    expect(noUnreadable).toMatchObject({ reason: 'offline' });
  });

  it('for an old board with no failure on record, says since the time the board was built', () => {
    const result = assess({ builtAgo: 240_000 });
    expect(result).toMatchObject({ reason: 'old', since: new Date(T - 240_000).toISOString() });
  });

  it('gives the build time, the best estimate of now and the age', () => {
    const result = assess({ builtAgo: 240_000 });
    expect(result).toMatchObject({
      asOf: new Date(T - 240_000).toISOString(),
      now: new Date(T).toISOString(),
      ageMs: 240_000,
    });
  });

  it('counts a board that stopped refreshing as last known even though the stream says it is open', () => {
    expect(assess({ builtAgo: 10 * 60_000, health: { streamDownSince: null } }).mode).toBe('last-known');
  });
});

describe('assessBoard: the back end clock, not the browser clock', () => {
  it('measures the age on the back end clock when the browser clock is an hour fast or slow', () => {
    for (const offset of [-3_600_000, 3_600_000, 90_000]) {
      expect(assess({ offset, builtAgo: 60_000 })).toEqual({ mode: 'live', streamPaused: false });
      expect(assess({ offset, builtAgo: STALE_AFTER_MS + 1 })).toMatchObject({ mode: 'last-known', reason: 'old' });
    }
  });

  it('reports the failure time on the back end clock', () => {
    const offset = 3_600_000;
    const result = assess({ offset, health: { streamDownSince: T - 20_000, failingSince: T - 5_000 } });
    expect(result).toMatchObject({ since: new Date(T - 5_000 + offset).toISOString() });
  });

  it('refuses a board built in the future, in the same way as an unreadable one, but allows a minute of skew', () => {
    const future = assessBoard({
      generatedAt: new Date(T + MAX_FUTURE_SKEW_MS + 1).toISOString(),
      nowLocal: T,
      clockOffsetMs: 0,
      health: NONE,
    });
    expect(future).toMatchObject({ mode: 'last-known', reason: 'unreadable' });

    const allowed = assessBoard({
      generatedAt: new Date(T + MAX_FUTURE_SKEW_MS).toISOString(),
      nowLocal: T,
      clockOffsetMs: 0,
      health: NONE,
    });
    expect(allowed.mode).toBe('live');
  });
});

describe('assessBoard: London clock changes (instants, never local times)', () => {
  function between(generatedAt: string, now: string) {
    return assessBoard({ generatedAt, nowLocal: Date.parse(now), clockOffsetMs: 0, health: NONE });
  }

  it('spring forward, 2026-03-29: 00:58:30 to 01:01:30 UTC is 3 minutes though London goes from 00:58 to 02:01', () => {
    const edge = between('2026-03-29T00:58:30Z', '2026-03-29T01:01:30Z');
    expect(edge).toEqual({ mode: 'live', streamPaused: false });

    const over = between('2026-03-29T00:58:30Z', '2026-03-29T01:01:31Z');
    expect(over).toMatchObject({ mode: 'last-known', reason: 'old', ageMs: 181_000 });
  });

  it('autumn back, 2026-10-25: 00:59 UTC (01:59 BST) to 01:02:30 UTC (01:02 GMT) is 3.5 minutes, not minus 57', () => {
    const result = between('2026-10-25T00:59:00Z', '2026-10-25T01:02:30Z');
    expect(result).toMatchObject({ mode: 'last-known', reason: 'old', ageMs: 210_000 });
  });

  it('autumn back: the repeated hour 01:00 to 02:00 gives the right age for a board from the first pass', () => {
    const result = between('2026-10-25T00:30:00Z', '2026-10-25T01:30:00Z');
    expect(result).toMatchObject({ mode: 'last-known', ageMs: 3_600_000 });
  });

  it('across midnight, 2026-10-24 23:59 to 2026-10-25 00:01 UTC, a board is 2 minutes old and live', () => {
    expect(between('2026-10-24T23:59:00Z', '2026-10-25T00:01:00Z')).toEqual({ mode: 'live', streamPaused: false });
  });
});
