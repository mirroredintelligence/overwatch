// Trace context for the browser (O02). Every request to /api/bff/* carries a W3C traceparent
// (https://www.w3.org/TR/trace-context/): version 00, a 16-byte trace id, an 8-byte parent id and
// the sampled flag. The requests of one interaction (a tap, a submit) share a trace id for a few
// seconds, so the event that records the tap and the back-end spans it caused can be joined.

const SAMPLED = '01';
const INTERACTION_MS = 5000;

let interaction: { traceId: string; startedAt: number } | null = null;
let requestObserver: ((traceId: string) => void) | null = null;

function randomHex(bytes: number): string {
  const buffer = new Uint8Array(bytes);
  crypto.getRandomValues(buffer);
  return Array.from(buffer, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

// An all-zero id is invalid in the header, so it is drawn again (the odds are negligible).
function nonZeroHex(bytes: number): string {
  let value = randomHex(bytes);
  while (/^0+$/.test(value)) value = randomHex(bytes);
  return value;
}

export const TRACEPARENT_PATTERN = /^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/;

export function newTraceparent(): string {
  return `00-${nonZeroHex(16)}-${nonZeroHex(8)}-${SAMPLED}`;
}

/** Starts a new interaction: its requests share one trace id for INTERACTION_MS. */
export function beginInteraction(): string {
  const traceId = nonZeroHex(16);
  interaction = { traceId, startedAt: Date.now() };
  return traceId;
}

/** The trace id of the interaction in progress, or null when none is recent. */
export function currentTraceId(): string | null {
  if (interaction === null) return null;
  if (Date.now() - interaction.startedAt >= INTERACTION_MS) return null;
  return interaction.traceId;
}

/** Told the trace id of every request that goes through withTraceparent (for the event classifier). */
export function setRequestObserver(observer: ((traceId: string) => void) | null): void {
  requestObserver = observer;
}

function traceIdOf(traceparent: string): string {
  return traceparent.split('-')[1] ?? '';
}

/**
 * The init for a request to the BFF: the same init with a traceparent header added. The caller's own
 * headers are kept, and a traceparent the caller already set is not replaced.
 */
export function withTraceparent(init: RequestInit = {}): RequestInit {
  const headers = new Headers(init.headers);
  if (!headers.has('traceparent')) {
    const traceId = currentTraceId() ?? nonZeroHex(16);
    headers.set('traceparent', `00-${traceId}-${nonZeroHex(8)}-${SAMPLED}`);
  }
  const traceparent = headers.get('traceparent') ?? '';
  requestObserver?.(traceIdOf(traceparent));
  return { ...init, headers };
}
