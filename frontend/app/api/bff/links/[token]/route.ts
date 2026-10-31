import { checkLinkCsrf, issueLinkCsrf, renewCsrfFor } from '@/lib/links/csrf';
import { type ClosedLink, parseClosed, parseLinkAnswered } from '@/lib/links/model';
import { callLinkApi, hostOf, publicReply, readLink } from '@/lib/links/server';
import { sealThanks } from '@/lib/links/thanks';

// The capacity link page's own API. No session: the link's token is the only thing that says
// which link this is, and the tenant is the host the request was addressed to, which the back
// end reads (DEC-167). Nothing here reads a tenant, a scope or an organisation from the request.

const NO_STORE = { 'Cache-Control': 'no-store' };
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;
const ANSWER_FIELDS = ['action', 'value', 'confirmOutOfRange', 'reason'] as const;
// The answers a link takes, and the value and reason each may carry (KI-178). The back end checks them
// again; this stops what is not an answer before it is asked.
const ACTIONS = ['confirm', 'number', 'closed', 'decline', 'withdraw', 'not-reached'] as const;
const REASON = /^[a-z][a-z-]{0,39}$/;
const MAX_FIGURE = 999;
const MAX_BODY_BYTES = 1024;

type Context = { params: Promise<{ token: string }> };

function reply(result: { status: number; body: Record<string, unknown> }, retryAfter?: string): Response {
  const headers: Record<string, string> = { ...NO_STORE };
  if (result.status === 429 && retryAfter !== undefined && /^\d{1,6}$/.test(retryAfter)) {
    headers['Retry-After'] = retryAfter;
  }
  return Response.json(result.body, { status: result.status, headers });
}

const unavailable = () => reply({ status: 503, body: { state: 'unavailable' } });

/**
 * A closed link: its state word, what it says of its closing (booking links only), and the CSRF token of
 * its renewal. Every closed or unknown link gets a token, so it says nothing of which links exist. With no
 * secret to make the token, the answer is the state and the details alone, and no renewal can be asked.
 */
function gone(token: string, closed: ClosedLink = parseClosed(undefined)): Response {
  const body: Record<string, unknown> = { state: closed.state };
  if (closed.kind !== null) body.kind = closed.kind;
  for (const field of ['reference', 'closedAt', 'confirmedAt', 'cancelledAt', 'coordinationPhone'] as const) {
    if (closed[field] !== null) body[field] = closed[field];
  }
  try {
    body.csrfToken = renewCsrfFor(token);
  } catch {
    // no secret: no token
  }
  return reply({ status: 410, body });
}
const forbidden = () => reply({ status: 403, body: { state: 'forbidden' } });
const invalid = () => reply({ status: 400, body: { state: 'invalid' } });

/**
 * Reads the link: what it is about, and its CSRF token. This is the browser's one read of the link,
 * so the CSRF cookie is set by a response the browser asked for; it changes nothing on the back end.
 */
export async function GET(request: Request, context: Context): Promise<Response> {
  const { token } = await context.params;
  if (!TOKEN_SHAPE.test(token)) return gone(token);
  try {
    const state = await readLink(token, hostOf(request));
    if (state.kind === 'gone') return gone(token, state.closed);
    await issueLinkCsrf(token, state.link.view.csrfToken);
    return reply({ status: 200, body: { ...state.link.view } });
  } catch {
    return unavailable();
  }
}

/**
 * Records one answer. The CSRF header must equal this link's cookie; the back end then checks it
 * against the link. Only the answer's own fields are forwarded, never anything else in the body.
 */
export async function POST(request: Request, context: Context): Promise<Response> {
  const { token } = await context.params;
  if (!TOKEN_SHAPE.test(token) || !checkLinkCsrf(request, token)) return forbidden();

  const text = await request.text();
  if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) return invalid();
  let parsed: unknown;
  try {
    parsed = JSON.parse(text) as unknown;
  } catch {
    return invalid();
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return invalid();
  const source = parsed as Record<string, unknown>;
  const answer: Record<string, unknown> = {};
  for (const field of ANSWER_FIELDS) {
    if (field in source) answer[field] = source[field];
  }
  if (!isAnswer(answer)) return invalid();

  try {
    const reply_ = await callLinkApi({
      method: 'POST',
      path: `/links/${token}`,
      host: hostOf(request),
      body: answer,
      csrf: request.headers.get('X-CSRF-Token') ?? undefined,
    });
    const result = publicReply(reply_.status, reply_.body);
    await sealRecorded(result);
    addRenewalToken(result, token);
    return reply(result, reply_.retryAfter);
  } catch {
    return unavailable();
  }
}

/**
 * Whether what the browser sent is an answer a link takes (KI-178): a known action; a whole figure from 0
 * to 999 with a `number` and with nothing else; `confirmOutOfRange` true or false; a reason only with the
 * actions that take one, and as a code. Anything else is refused here, before the back end is asked.
 */
function isAnswer(answer: Record<string, unknown>): boolean {
  const { action, value, confirmOutOfRange, reason } = answer;
  if (typeof action !== 'string' || !(ACTIONS as readonly string[]).includes(action)) return false;
  if (action === 'number') {
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value > MAX_FIGURE) return false;
  } else if (value !== undefined) {
    return false;
  }
  if (confirmOutOfRange !== undefined && (typeof confirmOutOfRange !== 'boolean' || action !== 'number')) return false;
  if (reason !== undefined) {
    if (typeof reason !== 'string' || !REASON.test(reason)) return false;
    if (!['decline', 'withdraw', 'not-reached'].includes(action)) return false;
  }
  return true;
}

/** An answer to a link that has closed carries the CSRF token of its renewal, as a read of it does. */
function addRenewalToken(result: { status: number; body: Record<string, unknown> }, token: string): void {
  if (result.status !== 410) return;
  try {
    result.body.csrfToken = renewCsrfFor(token);
  } catch {
    // no secret: no token
  }
}

/**
 * A recorded figure carries the detail of the thank-you page, sealed (KI-179). Without a secret to seal
 * it with, the answer is as it was and the page says only thank you.
 */
async function sealRecorded(result: { status: number; body: Record<string, unknown> }): Promise<void> {
  if (result.status !== 200 || !('recordedAt' in result.body)) return;
  try {
    result.body.thanks = await sealThanks(parseLinkAnswered(result.body));
  } catch {
    // not sealed: no detail
  }
}
