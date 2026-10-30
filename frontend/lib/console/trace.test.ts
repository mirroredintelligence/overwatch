import { describe, expect, it } from 'vitest';
import { QUERY_BUDGET_MS, layoutSpan, slowestSpan } from './trace';

describe('layoutSpan', () => {
  it('places a 1.2 s span that starts at 0.6 s at 25% left and 50% width of a 2.4 s trace', () => {
    expect(layoutSpan({ offsetMs: 600, durationMs: 1200 }, 2400)).toEqual({ leftPct: 25, widthPct: 50 });
  });

  it('keeps a span inside the trace: its right edge never passes 100%', () => {
    const { leftPct, widthPct } = layoutSpan({ offsetMs: 2000, durationMs: 900 }, 2400);

    expect(leftPct + widthPct).toBeLessThanOrEqual(100);
  });
});

describe('slowestSpan', () => {
  it('names the slowest span, which the page compares with the query budget', () => {
    const slowest = slowestSpan([
      { spanId: 'a', parentSpanId: null, name: 'POST /api/bff/bookings', offsetMs: 0, durationMs: 2400, status: 'ok' },
      { spanId: 'b', parentSpanId: 'a', name: 'Cypher BookingRequest', offsetMs: 600, durationMs: 1200, status: 'ok' },
    ]);

    expect(slowest?.name).toBe('POST /api/bff/bookings');
  });

  it('answers null for a trace with no spans', () => {
    expect(slowestSpan([])).toBeNull();
  });

  it('uses the 200 ms budget for a named Cypher query (observability.md, options)', () => {
    expect(QUERY_BUDGET_MS).toBe(200);
  });
});
