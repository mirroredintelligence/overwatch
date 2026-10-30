import { readToken, sessionEnd } from '@/lib/auth/exchange';
import { callLinkApi, LinkApiError, type LinkReply } from '@/lib/links/server';

// Server-only. The BFF's calls to the back end's wall screen routes (R15, DEC-224) and to the token
// exchange for a paired screen (TEN-043, DEC-526). The tenant of every call that has no token of its
// own is the host the browser came to, which `callLinkApi` sends as the Host header; a call that has
// a token (a lead's connect) is the token's tenant and sends the same host harmlessly. Every answer
// is checked before it is used, and every failure is one of a few kinds: no error holds a token, a
// code, a secret or a word the back end said.

export type ScreenFailure = 'not-found' | 'throttled' | 'invalid' | 'unauthorised' | 'unavailable' | 'bad-answer';

export class ScreenApiError extends Error {
  readonly kind: ScreenFailure;
  /** Seconds the back end asks to wait, digits only, when it said. */
  readonly retryAfter?: string;

  constructor(kind: ScreenFailure, retryAfter?: string) {
    super('The screen request failed.');
    this.name = 'ScreenApiError';
    this.kind = kind;
    this.retryAfter = retryAfter;
  }
}

const PAIRING_ID = /^[A-Za-z0-9_-]{1,64}$/;
const CODE = /^[0-9]{6}$/;
const VISIBLE = /^[\x21-\x7e]+$/;
const SECRET_MAX = 256;
const TOKEN_MAX = 1024;
const NAME_MAX = 120;
const RETRY_AFTER = /^\d{1,6}$/;

async function call(request: Parameters<typeof callLinkApi>[0]): Promise<LinkReply> {
  try {
    return await callLinkApi(request);
  } catch (error) {
    if (error instanceof LinkApiError) throw new ScreenApiError('unavailable');
    throw error; // A missing back-end address is a set-up fault, named by its variable.
  }
}

/** The failure an answer that is not the one wanted stands for. */
function failure(reply: LinkReply, own: { invalid?: boolean; unauthorised?: boolean } = {}): ScreenApiError {
  if (reply.status === 404) return new ScreenApiError('not-found');
  if (reply.status === 429) {
    return new ScreenApiError('throttled', reply.retryAfter !== undefined && RETRY_AFTER.test(reply.retryAfter) ? reply.retryAfter : undefined);
  }
  if (own.invalid && (reply.status === 400 || reply.status === 422)) return new ScreenApiError('invalid');
  if (own.unauthorised && (reply.status === 401 || reply.status === 403)) return new ScreenApiError('unauthorised');
  return new ScreenApiError('unavailable');
}

function fields(body: unknown): Record<string, unknown> {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) throw new ScreenApiError('bad-answer');
  return body as Record<string, unknown>;
}

export type StartedPairing = { pairingId: string; code: string; expiresAt: string; screenSecret: string };

/** The display asks for a code. No token: the host names the tenant. */
export async function startPairing(host: string | null): Promise<StartedPairing> {
  const reply = await call({ method: 'POST', path: '/screens/pairing', host, body: {} });
  if (reply.status !== 201) throw failure(reply);
  const { pairingId, code, expiresAt, screenSecret } = fields(reply.body);
  if (typeof pairingId !== 'string' || !PAIRING_ID.test(pairingId)) throw new ScreenApiError('bad-answer');
  if (typeof code !== 'string' || !CODE.test(code)) throw new ScreenApiError('bad-answer');
  if (typeof screenSecret !== 'string' || !VISIBLE.test(screenSecret) || screenSecret.length > SECRET_MAX) throw new ScreenApiError('bad-answer');
  const expires = typeof expiresAt === 'string' ? Date.parse(expiresAt) : Number.NaN;
  if (Number.isNaN(expires)) throw new ScreenApiError('bad-answer');
  return { pairingId, code, expiresAt: new Date(expires).toISOString(), screenSecret };
}

export type Claim = { status: 'waiting' } | { status: 'expired' } | { status: 'paired'; deviceToken: string | null };

/** The display asks whether a lead has connected it. The secret goes in the header, never the address. */
export async function claimPairing(host: string | null, pairingId: string, screenSecret: string): Promise<Claim> {
  if (!PAIRING_ID.test(pairingId) || !VISIBLE.test(screenSecret) || screenSecret.length > SECRET_MAX) {
    throw new ScreenApiError('not-found');
  }
  const reply = await call({
    method: 'GET',
    path: `/screens/pairing/${pairingId}`,
    host,
    headers: { 'X-Screen-Secret': screenSecret },
  });
  if (reply.status !== 200) throw failure(reply);
  const { status, deviceToken } = fields(reply.body);
  if (status === 'waiting' || status === 'expired') {
    if (deviceToken !== undefined) throw new ScreenApiError('bad-answer');
    return { status };
  }
  if (status !== 'paired') throw new ScreenApiError('bad-answer');
  if (deviceToken === undefined) return { status, deviceToken: null };
  if (typeof deviceToken !== 'string' || !VISIBLE.test(deviceToken) || deviceToken.length > TOKEN_MAX) {
    throw new ScreenApiError('bad-answer');
  }
  return { status, deviceToken };
}

export type WallGrant = { token: string; expiresAt: string; sub: string };

/** A paired screen trades its device token for the one-hour wall token the back end signs. */
export async function exchangeDeviceToken(host: string | null, deviceToken: string, now: Date = new Date()): Promise<WallGrant> {
  if (!VISIBLE.test(deviceToken) || deviceToken.length > TOKEN_MAX) throw new ScreenApiError('not-found');
  const reply = await call({
    method: 'POST',
    path: '/auth/device-token',
    host,
    body: {},
    headers: { Authorization: `Bearer ${deviceToken}` },
  });
  // A limit on exchanges from the BFF's address is not the screen's to be told: it asks again later.
  if (reply.status !== 200) throw reply.status === 429 ? new ScreenApiError('unavailable') : failure(reply);
  const { token, expiresAt, role } = fields(reply.body);
  if (role !== 'wall' || typeof token !== 'string' || typeof expiresAt !== 'string') throw new ScreenApiError('bad-answer');
  const claims = readToken(token);
  const ends = claims === null ? null : sessionEnd(expiresAt, claims.expiresAtMs, now);
  if (claims === null || ends === null) throw new ScreenApiError('bad-answer');
  return { token, expiresAt: ends, sub: claims.sub };
}

export type ConnectInput = { code: string; name: string; location: string | null };

/** A shift lead connects the code a display shows. The lead's own token names the tenant. */
export async function connectScreen(
  host: string | null,
  leadToken: string,
  input: ConnectInput,
  idempotencyKey: string,
): Promise<{ name: string; status: 'online' }> {
  const body: Record<string, string> = { code: input.code, name: input.name };
  if (input.location !== null) body.location = input.location;
  const reply = await call({
    method: 'POST',
    path: '/screens',
    host,
    body,
    headers: { Authorization: `Bearer ${leadToken}`, 'Idempotency-Key': idempotencyKey },
  });
  if (reply.status !== 201) throw failure(reply, { invalid: true, unauthorised: true });
  const { name, status } = fields(reply.body);
  if (status !== 'online' || typeof name !== 'string' || name.length === 0 || name.length > NAME_MAX) {
    throw new ScreenApiError('bad-answer');
  }
  return { name, status };
}
