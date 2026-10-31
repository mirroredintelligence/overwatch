import { withTraceparent } from '@/lib/telemetry/trace';
import { type BookingView, type ClosedLink, type LinkAnswer, type LinkAnswered, type LinkView, parseClosed, parseLinkAnswered, parseOpenLink } from './model';

// The browser's calls to the link pages' BFF (`/api/bff/links/[token]`). Each answers with what the
// page needs to show, and nothing else: a token, a hash or a tenant never comes back through here.

export type AnswerOutcome =
  | { kind: 'recorded'; answered: LinkAnswered; thanks: string | null }
  | { kind: 'out-of-range'; usualMin: number; usualMax: number }
  | { kind: 'send-number' }
  | { kind: 'gone'; csrfToken: string | null }
  | { kind: 'rate-limited' }
  | { kind: 'failed' };

const CAPACITY_PURPOSE = 'capacity-reply';

const base = (token: string) => `/api/bff/links/${encodeURIComponent(token)}`;

export type LinkRead =
  | { kind: 'open'; view: LinkView }
  | { kind: 'booking'; view: BookingView }
  | { kind: 'gone'; closed: ClosedLink; csrfToken: string | null }
  | { kind: 'unavailable' };

/** A booking answer (L02): a confirm or a decline, or a withdrawal or not-reached report with its reason. */
export type BookingAnswer =
  | { action: 'confirm' }
  | { action: 'decline'; reason?: string }
  | { action: 'withdraw'; reason: string }
  | { action: 'not-reached'; reason: string };

/** What the page shows after a booking answer. A conflict carries the booking's state word. */
export type BookingOutcome =
  | { kind: 'answered'; bookingStatus: string; changeToken?: string; confirmedAt?: string; respondedAt?: string }
  | { kind: 'gone'; closed: ClosedLink }
  | { kind: 'conflict'; state: string; closed: ClosedLink }
  | { kind: 'rate-limited' }
  | { kind: 'failed' };

/**
 * Reads the link through the BFF: the browser's own request, so the CSRF cookie for this link is set
 * by a response the browser asked for. One back-end read per page view (DEC-167 item 8 limits them).
 */
export async function readLinkView(token: string): Promise<LinkRead> {
  let response: Response;
  try {
    response = await fetch(base(token), withTraceparent({ method: 'GET', cache: 'no-store', credentials: 'same-origin' }));
  } catch {
    return { kind: 'unavailable' };
  }
  if (response.status === 410) {
    const body = await bodyOf(response);
    return { kind: 'gone', closed: parseClosed(body), csrfToken: csrfOf(body) };
  }
  if (!response.ok) return { kind: 'unavailable' };
  try {
    const page = parseOpenLink(await response.json());
    if (page.kind === 'booking') return { kind: 'booking', view: page.view };
    // A capacity page serves only the capacity-reply purpose; anything else is not a link this page reads.
    return page.view.purpose === CAPACITY_PURPOSE ? { kind: 'open', view: page.view } : { kind: 'unavailable' };
  } catch {
    return { kind: 'unavailable' };
  }
}

/** The renewal CSRF token of a closed link's answer, or null when it carries none. */
function csrfOf(body: unknown): string | null {
  const token = typeof body === 'object' && body !== null ? (body as { csrfToken?: unknown }).csrfToken : undefined;
  return typeof token === 'string' && /^[A-Za-z0-9._-]{8,128}$/.test(token) ? token : null;
}

function timeOf(value: unknown): string | undefined {
  return typeof value === 'string' && value.length <= 40 && !Number.isNaN(Date.parse(value)) ? value : undefined;
}

/** Sends one booking answer. Nothing from the answer is kept; the outcome says what the page shows. */
export async function sendBookingAnswer(token: string, csrf: string, answer: BookingAnswer): Promise<BookingOutcome> {
  let response: Response;
  try {
    response = await fetch(base(token), withTraceparent({
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify(answer),
      cache: 'no-store',
      credentials: 'same-origin',
    }));
  } catch {
    return { kind: 'failed' };
  }
  const body = await bodyOf(response);
  switch (response.status) {
    case 200: {
      const record = body as { bookingStatus?: unknown; changeToken?: unknown; confirmedAt?: unknown; respondedAt?: unknown } | undefined;
      if (typeof record?.bookingStatus !== 'string') return { kind: 'failed' };
      const answered: BookingOutcome = { kind: 'answered', bookingStatus: record.bookingStatus };
      if (typeof record.changeToken === 'string') answered.changeToken = record.changeToken;
      const confirmedAt = timeOf(record.confirmedAt);
      if (confirmedAt !== undefined) answered.confirmedAt = confirmedAt;
      const respondedAt = timeOf(record.respondedAt);
      if (respondedAt !== undefined) answered.respondedAt = respondedAt;
      return answered;
    }
    case 409: {
      const closed = parseClosed(body);
      return { kind: 'conflict', state: closed.state, closed };
    }
    case 410:
      return { kind: 'gone', closed: parseClosed(body) };
    case 429:
      return { kind: 'rate-limited' };
    default:
      return { kind: 'failed' };
  }
}

async function bodyOf(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    return undefined;
  }
}

/** Sends one answer. The outcome says what the page should show; nothing from the answer is kept. */
export async function sendAnswer(token: string, csrf: string, answer: LinkAnswer): Promise<AnswerOutcome> {
  let response: Response;
  try {
    response = await fetch(base(token), withTraceparent({
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify(answer),
      cache: 'no-store',
      credentials: 'same-origin',
    }));
  } catch {
    return { kind: 'failed' };
  }
  const body = await bodyOf(response);
  switch (response.status) {
    case 200:
      try {
        const sealed = (body as { thanks?: unknown } | undefined)?.thanks;
        return { kind: 'recorded', answered: parseLinkAnswered(body), thanks: typeof sealed === 'string' ? sealed : null };
      } catch {
        return { kind: 'failed' };
      }
    case 422: {
      const range = body as { usualMin?: unknown; usualMax?: unknown } | undefined;
      if (typeof range?.usualMin === 'number' && typeof range.usualMax === 'number') {
        return { kind: 'out-of-range', usualMin: range.usualMin, usualMax: range.usualMax };
      }
      return { kind: 'failed' };
    }
    case 409:
      return { kind: 'send-number' };
    case 410:
      return { kind: 'gone', csrfToken: csrfOf(body) };
    case 429:
      return { kind: 'rate-limited' };
    default:
      return { kind: 'failed' };
  }
}

/**
 * Asks for a new link to an expired link, with the renewal CSRF token the closed link gave the page
 * (KI-178). The back end answers 202 for every token; 429 when the budget is spent.
 */
export async function requestRenew(token: string, csrf: string): Promise<'accepted' | 'rate-limited' | 'failed'> {
  try {
    const response = await fetch(
      `${base(token)}/renew`,
      withTraceparent({ method: 'POST', headers: { 'X-CSRF-Token': csrf }, cache: 'no-store', credentials: 'same-origin' }),
    );
    if (response.status === 202) return 'accepted';
    return response.status === 429 ? 'rate-limited' : 'failed';
  } catch {
    return 'failed';
  }
}
