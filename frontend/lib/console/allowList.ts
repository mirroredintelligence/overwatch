// What the console may render from one timeline event (W48). The back end already keeps only
// element ids, route templates and outcomes; this is the second list, so a field the API adds later
// (a value, a text, a name) is never shown. Nothing a person typed is ever in this list.

export type ConsoleEvent = {
  kind: string;
  offsetMs: number;
  elementId?: string;
  route?: string;
  outcome?: string;
  durationMs?: number;
  status?: string;
  /** The trace of an API call, when the back end sends one. Used only for the View trace link. */
  traceId?: string;
};

function textOf(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function numberOf(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/** One event with only the allow-listed fields. Null for an event with no kind or offset. */
export function pickAllowed(event: Record<string, unknown>): ConsoleEvent | null {
  const kind = textOf(event.kind);
  const offsetMs = numberOf(event.offsetMs);
  if (kind === undefined || offsetMs === undefined) return null;
  const kept: ConsoleEvent = { kind, offsetMs };
  const elementId = textOf(event.elementId);
  const route = textOf(event.route);
  const outcome = textOf(event.outcome);
  const status = textOf(event.status);
  const traceId = textOf(event.traceId);
  const durationMs = numberOf(event.durationMs);
  if (elementId !== undefined) kept.elementId = elementId;
  if (route !== undefined) kept.route = route;
  if (outcome !== undefined) kept.outcome = outcome;
  if (status !== undefined) kept.status = status;
  if (traceId !== undefined) kept.traceId = traceId;
  if (durationMs !== undefined) kept.durationMs = durationMs;
  return kept;
}
