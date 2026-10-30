// Stub (red commit): the layout and the budget are not built yet.
export const QUERY_BUDGET_MS = 0;

export type SpanView = {
  spanId: string;
  parentSpanId: string | null;
  name: string;
  offsetMs: number;
  durationMs: number;
  status: string;
};

export function layoutSpan(span: { offsetMs: number; durationMs: number }, totalMs: number) {
  void span;
  void totalMs;
  return { leftPct: 0, widthPct: 0 };
}

export function slowestSpan(spans: SpanView[]): SpanView | null {
  void spans;
  return null;
}
