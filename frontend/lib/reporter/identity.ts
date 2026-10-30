import { callLinkApi, hostOf, LinkApiError, type LinkReply } from '@/lib/links/server';
import { json, plain } from './backend';

// The back end's reporter identity routes (R11, R13, W7C), called by the BFF. They sit beside /fhir, at
// the back end's root, and the tenant is the host the browser addressed (DEC-134 item 3), so the BFF
// passes that host and nothing the browser sends. A device id is passed in the body or the
// X-Device-Id header, never in the URL. The answers of the text-code routes are mapped here, once, for
// the set-up, the 30-day check, the locked PIN and the lost phone.

export type IdentityReply = LinkReply;

export function identityCall(
  request: Request,
  call: { method: 'GET' | 'POST'; path: string; body?: unknown; headers?: Record<string, string> },
): Promise<IdentityReply> {
  return callLinkApi({ ...call, host: hostOf(request) });
}

/** A call whose failure to connect is a 503 answer, not a thrown fault. */
export async function identityOrUnavailable(
  request: Request,
  call: { method: 'GET' | 'POST'; path: string; body?: unknown },
): Promise<IdentityReply | Response> {
  try {
    return await identityCall(request, call);
  } catch (error) {
    if (error instanceof LinkApiError) return plain(503, 'unavailable');
    throw error;
  }
}

export const throttled = (reply: IdentityReply): Response =>
  json({ code: 'throttled' }, 429, reply.retryAfter !== undefined && /^\d{1,6}$/.test(reply.retryAfter) ? { 'Retry-After': reply.retryAfter } : {});

/** The answer to a request for a code: 202 is the back end's, anything else says the code was not sent. */
export function codeRequested(reply: IdentityReply): Response {
  if (reply.status === 202) {
    const wait = (reply.body as { resendAfterSeconds?: unknown } | undefined)?.resendAfterSeconds;
    const seconds = typeof wait === 'number' && Number.isInteger(wait) && wait >= 1 && wait <= 3600 ? wait : 60;
    return json({ accepted: true, resendAfterSeconds: seconds }, 202);
  }
  if (reply.status === 429) return throttled(reply);
  return plain(503, 'unavailable');
}

function triesLeftOf(body: unknown): number | undefined {
  if (typeof body !== 'object' || body === null) return undefined;
  const { triesLeft, issue } = body as { triesLeft?: unknown; issue?: unknown };
  const first = Array.isArray(issue) ? (issue[0] as { diagnostics?: unknown } | undefined) : undefined;
  // Five wrong tries and a lapsed code are both "ask for a new code": no tries left.
  if (typeof first?.diagnostics === 'string' && /ask for a new code/i.test(first.diagnostics)) return 0;
  return typeof triesLeft === 'number' && Number.isInteger(triesLeft) && triesLeft >= 0 && triesLeft <= 10 ? triesLeft : undefined;
}

/** The answer to a code check: ok, not ok with the tries left, a phone that cannot take it, or not checked. */
export function codeChecked(reply: IdentityReply): Response {
  if (reply.status === 200) {
    return (reply.body as { verified?: unknown } | undefined)?.verified === true ? json({ ok: true }) : plain(503, 'unavailable');
  }
  if (reply.status === 400) {
    const left = triesLeftOf(reply.body);
    return json(left === undefined ? { ok: false } : { ok: false, triesLeft: left });
  }
  if (reply.status === 409) return plain(409, 'device-refused');
  if (reply.status === 429) return throttled(reply);
  return plain(503, 'unavailable');
}
