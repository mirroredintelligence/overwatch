import { BackendCallError, backendRoot, callBackend, type BackendCall, type BackendReply } from '@/lib/fhir/hostCall';
import { parseOpenLink, type OpenLink, LinkShapeError } from './model';

// Server-only. The link pages' route handlers and Server Components call the back end's
// link API (`/links/...`, beside `/fhir`) through this module, never the browser.
//
// The tenant is the host a request was addressed to (DEC-134 item 3, DEC-167 item 1), so the call
// sends the browser's host to the back end as its Host header (lib/fhir/hostCall.ts).

export { backendRoot };

export class LinkApiError extends Error {
  readonly kind: 'unavailable' | 'bad-answer';

  constructor(kind: 'unavailable' | 'bad-answer') {
    super('The link could not be read from the back end.');
    this.name = 'LinkApiError';
    this.kind = kind;
  }
}

/**
 * The host a request was addressed to: the Host header, or the host of its own URL when the
 * header is absent (a request built without one). Never a value from the body or the query.
 */
export function hostOf(request: Request): string | null {
  const header = request.headers.get('host');
  if (header !== null) return header;
  try {
    return new URL(request.url).host;
  } catch {
    return null;
  }
}

export type LinkReply = BackendReply;
export type LinkCall = BackendCall;

/**
 * One call to the back end's link API. Rejects with LinkApiError when the back end cannot be
 * reached, or the host is not a host name; a missing base URL rejects too.
 */
export async function callLinkApi(call: LinkCall): Promise<LinkReply> {
  try {
    return await callBackend(call);
  } catch (error) {
    if (error instanceof BackendCallError) throw new LinkApiError(error.kind);
    throw error;
  }
}

export type LinkState = { kind: 'open'; link: OpenLink } | { kind: 'gone'; state: ClosedState };

/**
 * The words a closed link may say on GET (L01, L02). A holder of the link may learn why it is closed
 * (a change link shows a cancelled booking); anything else the back end sends is `expired`.
 */
export const CLOSED_STATES = ['expired', 'used', 'declined', 'cancelled', 'withdrawn', 'not-reached'] as const;
export type ClosedState = (typeof CLOSED_STATES)[number];

export function closedStateOf(body: unknown): ClosedState {
  const state = typeof body === 'object' && body !== null ? (body as { state?: unknown }).state : undefined;
  return CLOSED_STATES.find((known) => known === state) ?? 'expired';
}

/** The link as the back end sees it for this host: open with its view, or gone (expired, used or unknown). */
export async function readLink(token: string, host: string | null): Promise<LinkState> {
  const reply = await callLinkApi({ method: 'GET', path: `/links/${encodeURIComponent(token)}`, host });
  if (reply.status === 410) return { kind: 'gone', state: closedStateOf(reply.body) };
  if (reply.status !== 200) throw new LinkApiError('unavailable');
  try {
    return { kind: 'open', link: parseOpenLink(reply.body) };
  } catch (error) {
    if (error instanceof LinkShapeError) throw new LinkApiError('bad-answer');
    throw error;
  }
}

const STATE_WORD = /^[a-z-]{1,24}$/;

/** The fields a page may read, per status. Anything else the back end sent is dropped. */
const FIELDS_BY_STATUS: Record<number, readonly string[]> = {
  200: [
    'bookingStatus',
    'changeToken',
    'serviceName',
    'value',
    'unitLabel',
    'recordedAt',
    'nextDue',
    'state',
    'purpose',
    'recordedValue',
    'asOf',
    'usualMin',
    'usualMax',
    'replyBy',
    'csrfToken',
  ],
  202: ['state'],
  400: ['state'],
  403: ['state'],
  409: ['state', 'reason', 'message'],
  410: ['state'],
  422: ['state', 'usualMin', 'usualMax'],
  429: ['state'],
};

/** What the browser is told: the status, and only the fields a page reads, or a fixed state word. */
export function publicReply(status: number, body: unknown): { status: number; body: Record<string, unknown> } {
  const fields = FIELDS_BY_STATUS[status];
  if (fields === undefined) {
    return { status, body: { state: status >= 500 ? 'error' : 'invalid' } };
  }
  const source = typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : {};
  const out: Record<string, unknown> = {};
  for (const field of fields) {
    if (!(field in source)) continue;
    const value = source[field];
    if (field === 'state' && (typeof value !== 'string' || !STATE_WORD.test(value))) continue;
    out[field] = value;
  }
  return { status, body: out };
}
