// Layout and budget for a trace waterfall (W48). Times are offsets from the trace's first span.

/** The budget for a named Cypher query on the options path (observability.md, Performance). */
export const QUERY_BUDGET_MS = 200;

export type SpanView = {
  spanId: string;
  parentSpanId: string | null;
  name: string;
  offsetMs: number;
  durationMs: number;
  status: string;
};

/** Where a span sits in the trace, as percentages of the trace's total. */
export function layoutSpan(span: { offsetMs: number; durationMs: number }, totalMs: number): {
  leftPct: number;
  widthPct: number;
} {
  if (!(totalMs > 0)) return { leftPct: 0, widthPct: 0 };
  const leftPct = clamp((span.offsetMs / totalMs) * 100);
  const widthPct = clamp((span.durationMs / totalMs) * 100, 0, 100 - leftPct);
  return { leftPct, widthPct };
}

function clamp(value: number, low = 0, high = 100): number {
  return Math.min(high, Math.max(low, value));
}

/** The span that took longest; the first of equal ones. Null when there are no spans. */
export function slowestSpan(spans: readonly SpanView[]): SpanView | null {
  let slowest: SpanView | null = null;
  for (const span of spans) {
    if (slowest === null || span.durationMs > slowest.durationMs) slowest = span;
  }
  return slowest;
}

/** A duration for a person to read: "812 ms" under a second, "1.2 s" from a second. */
export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** An offset as mm:ss, as the timeline shows it ("00:44"). */
export function formatOffset(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}
