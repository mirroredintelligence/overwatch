import { readIssuedToken } from '@/lib/auth/tokenClaims';
import { PIN_SESSION_PATTERN } from '@/lib/auth/session';
import { BackendCallError, callBackend } from '@/lib/fhir/hostCall';

// Server-only. A live PIN session is exchanged for a short reporter token (W7B A2, DEC-792): the
// back end signs it, the BFF holds no secret that could, and the person, tenant and phone it is for
// are the ones the session was made for. This is the one place that believes (or does not) what the
// back end answers; the sign-in and the renewal both go through it.
//
// What is sent is the PIN session id, and the host the phone came to (the tenant is the host's,
// DEC-134 item 3), with no bearer. What comes back is believed only when it is a reporter token
// (aud, role, tenant, device, expiry) for the tenant and phone asked about and, on a renewal, the
// same person. Anything else is `invalid`, and nothing in a result holds the session id.

/** [ASSUMED] The longest a reporter token may be told to last. The back end gives 30 minutes (DEC-792). */
export const MAX_TOKEN_MS = 60 * 60_000;

export type ExchangeInput = {
  /** The back end's PIN session id (a secret: sent to the exchange and nowhere else). */
  pinSession: string;
  /** The host the session was made on: the back end's tenant. */
  host: string;
  /** The tenant the session is for: the token must be for the same. */
  tenantId: string;
  /** The phone the session is for: the token must name it. */
  device: string;
  /** On a renewal, the person the session is for: the token must be the same person's. */
  sub?: string;
};

export type Exchange =
  | { kind: 'issued'; token: string; tokenExpiresAt: string; sub: string; services: string[] }
  /** The back end says there is no such live session: it has ended. */
  | { kind: 'refused' }
  /** The back end could not say (unreachable, busy, an answer that is not JSON). Try again. */
  | { kind: 'unavailable' }
  /** The back end answered, and not with a token this side will keep. */
  | { kind: 'invalid' };

const invalid: Exchange = { kind: 'invalid' };
const isoSeconds = (ms: number) => new Date(Math.floor(ms / 1000) * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z');

/**
 * Asks the back end for a token for this PIN session. Rejects only for a fault of this side (the
 * back end's address is not set): every answer, including a failed call, is a result.
 */
export async function exchangeSessionToken(input: ExchangeInput, now: Date = new Date()): Promise<Exchange> {
  if (!PIN_SESSION_PATTERN.test(input.pinSession)) return { kind: 'refused' };

  let reply;
  try {
    reply = await callBackend({ method: 'POST', path: '/identity/session-token', host: input.host, body: { sessionId: input.pinSession } });
  } catch (error) {
    if (error instanceof BackendCallError) return { kind: 'unavailable' };
    throw error;
  }
  if (reply.status === 429 || reply.status >= 500 || reply.status < 200) return { kind: 'unavailable' };
  if (reply.status !== 200) return reply.status >= 400 ? { kind: 'refused' } : { kind: 'unavailable' };
  if (reply.body === undefined) return { kind: 'unavailable' };

  const body = reply.body;
  if (typeof body !== 'object' || body === null || Array.isArray(body)) return invalid;
  const { token, expiresAt, role } = body as Record<string, unknown>;
  if (role !== 'reporter' || typeof token !== 'string' || typeof expiresAt !== 'string') return invalid;

  const claims = readIssuedToken(token, now);
  if (claims === null || claims.role !== 'reporter') return invalid;
  if (claims.tenant !== input.tenantId) return invalid;
  if (claims.device === undefined || claims.device !== input.device) return invalid;
  if (input.sub !== undefined && claims.sub !== input.sub) return invalid;

  const answered = Date.parse(expiresAt);
  const tokenEnds = claims.exp * 1000;
  const limit = now.getTime() + MAX_TOKEN_MS;
  if (Number.isNaN(answered) || answered <= now.getTime() || answered > limit || tokenEnds > limit) return invalid;

  const ends = Math.floor(Math.min(answered, tokenEnds) / 1000) * 1000;
  if (ends <= now.getTime()) return invalid;
  return { kind: 'issued', token, tokenExpiresAt: isoSeconds(ends), sub: claims.sub, services: claims.services };
}
