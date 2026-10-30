import { checkLinkCsrf, issueLinkCsrf } from '@/lib/links/csrf';
import { callLinkApi, type ClosedState, hostOf, type LinkReply, publicReply, readLink } from '@/lib/links/server';

// The capacity link page's own API. No session: the link's token is the only thing that says
// which link this is, and the tenant is the host the request was addressed to, which the back
// end reads (DEC-167). Nothing here reads a tenant, a scope or an organisation from the request.

const NO_STORE = { 'Cache-Control': 'no-store' };
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;
const ANSWER_FIELDS = ['action', 'value', 'confirmOutOfRange', 'reason'] as const;
const MAX_BODY_BYTES = 1024;

type Context = { params: Promise<{ token: string }> };

function reply(result: { status: number; body: Record<string, unknown> }, retryAfter?: string): Response {
  const headers: Record<string, string> = { ...NO_STORE };
  if (result.status === 429 && retryAfter !== undefined && /^\d{1,6}$/.test(retryAfter)) {
    headers['Retry-After'] = retryAfter;
  }
  return Response.json(result.body, { status: result.status, headers });
}

function fromBackEnd(answer: LinkReply): Response {
  return reply(publicReply(answer.status, answer.body), answer.retryAfter);
}

const unavailable = () => reply({ status: 503, body: { state: 'unavailable' } });
const gone = (state: ClosedState = 'expired') => reply({ status: 410, body: { state } });
const forbidden = () => reply({ status: 403, body: { state: 'forbidden' } });
const invalid = () => reply({ status: 400, body: { state: 'invalid' } });

/**
 * Reads the link: what it is about, and its CSRF token. This is the browser's one read of the link,
 * so the CSRF cookie is set by a response the browser asked for; it changes nothing on the back end.
 */
export async function GET(request: Request, context: Context): Promise<Response> {
  const { token } = await context.params;
  if (!TOKEN_SHAPE.test(token)) return gone();
  try {
    const state = await readLink(token, hostOf(request));
    if (state.kind === 'gone') return gone(state.state);
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

  try {
    return fromBackEnd(
      await callLinkApi({
        method: 'POST',
        path: `/links/${token}`,
        host: hostOf(request),
        body: answer,
        csrf: request.headers.get('X-CSRF-Token') ?? undefined,
      }),
    );
  } catch {
    return unavailable();
  }
}
