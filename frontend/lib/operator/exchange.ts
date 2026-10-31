import { callLinkApi, LinkApiError } from '@/lib/links/server';
import { SignInRefused } from '@/lib/auth/oidc';
import { sessionEnd } from '@/lib/auth/exchange';
import { isOperatorRole, type OperatorRole } from './session';
import { decodeJwt } from 'jose';

// Server-only. The operator sign-in's last step (TEN-083, DEC-1000, DEC-1005): the BFF hands the back end the
// person's verified ID token from the OPERATOR directory and gets back the operator token the back end signed
// itself (`POST /auth/operator-token`, audience `diucs-ops`, one hour). The BFF holds no secret that can sign
// one and decides no role. The token must be an operator's: it names no tenant, epoch, service or device, and
// its role is the answer's and is one an operator has. Nothing here logs, and no error holds a token, a
// subject or a claim.

export const OPERATOR_AUDIENCE = 'diucs-ops';
const ID_TOKEN_MAX_LENGTH = 8192; // the back end refuses more (routes_auth.py)
const TOKEN_MAX_LENGTH = 4096;
const SUBJECT_MAX_LENGTH = 128;
const TOKEN_MAX_LIFETIME_MS = 12 * 3600_000;
const TENANT_CLAIMS = ['tenant', 'tenantId', 'epoch', 'services', 'device'] as const;

export type OperatorGrant = {
  token: string;
  /** ISO 8601 instant, to the second: when the session must end, no later than the token. */
  expiresAt: string;
  role: OperatorRole;
  /** The back end's own opaque account reference, read from the token it signed. */
  sub: string;
};

export type OperatorExchange = { kind: 'issued'; grant: OperatorGrant } | { kind: 'refused' };

/** The subject and expiry of an operator token the back end signed, or null when it is not one. Not a verification. */
function readOperatorToken(token: string, role: OperatorRole): { sub: string; expiresAtMs: number } | null {
  if (token.length === 0 || token.length > TOKEN_MAX_LENGTH || token.split('.').length !== 3) return null;
  try {
    const claims = decodeJwt(token);
    if (claims.aud !== OPERATOR_AUDIENCE) return null;
    if (TENANT_CLAIMS.some((name) => name in claims)) return null;
    if (claims.role !== role) return null;
    const { sub, exp } = claims;
    if (typeof sub !== 'string' || sub.length === 0 || sub.length > SUBJECT_MAX_LENGTH) return null;
    if (typeof exp !== 'number' || !Number.isFinite(exp)) return null;
    return { sub, expiresAtMs: exp * 1000 };
  } catch {
    return null;
  }
}

/**
 * Asks the back end for the operator's token. `refused` is its one answer for everyone it will not sign in (a
 * 403, whatever the cause). Any other failure, or an answer that is not what the contract says, is a
 * `SignInRefused` with a fixed reason.
 */
export async function exchangeOperatorToken(idToken: string, host: string | null, now: Date = new Date()): Promise<OperatorExchange> {
  if (typeof idToken !== 'string' || idToken.length === 0 || idToken.length > ID_TOKEN_MAX_LENGTH) throw new SignInRefused('bad-token');
  let reply;
  try {
    reply = await callLinkApi({ method: 'POST', path: '/auth/operator-token', host, body: { idToken } });
  } catch (error) {
    if (error instanceof LinkApiError) throw new SignInRefused('exchange-failed');
    throw error; // A missing back-end address is a set-up fault, named by its variable.
  }
  if (reply.status === 403) return { kind: 'refused' };
  if (reply.status !== 200) throw new SignInRefused('exchange-failed');

  const answer = reply.body;
  if (typeof answer !== 'object' || answer === null || Array.isArray(answer)) throw new SignInRefused('exchange-answer');
  const { token, expiresAt, role } = answer as Record<string, unknown>;
  if (typeof token !== 'string' || typeof expiresAt !== 'string' || !isOperatorRole(role)) throw new SignInRefused('exchange-answer');

  const claims = readOperatorToken(token, role);
  if (claims === null) throw new SignInRefused('exchange-answer');
  // An operator's token is for an hour: one that lasts more than twelve is not one this side believes.
  if (claims.expiresAtMs - now.getTime() > TOKEN_MAX_LIFETIME_MS) throw new SignInRefused('exchange-answer');
  const ends = sessionEnd(expiresAt, claims.expiresAtMs, now);
  if (ends === null) throw new SignInRefused('exchange-answer');
  return { kind: 'issued', grant: { token, expiresAt: ends, role, sub: claims.sub } };
}
