import { decodeJwt } from 'jose';
import { callLinkApi, LinkApiError } from '@/lib/links/server';
import { SignInRefused } from './oidc';
import type { Role } from './session';

// Server-only. The staff sign-in's last step (TEN-043, DEC-522 to DEC-526): the BFF hands the back
// end the person's verified ID token and gets back the tenant-bound token the back end signed
// itself. The BFF holds no secret that can sign one, decides no role and names no tenant: the tenant
// is the host the browser came to (the same host this request is addressed to, DEC-134 item 3), the
// directory must be the one that tenant has bound, and the role is that tenant's own mapping of the
// person's groups. Nothing here logs, and no error holds a token, a subject or a claim.

/** The roles the staff exchange gives that this front end has pages for. */
export const STAFF_ROLES: readonly Role[] = ['advisor', 'clinical', 'lead', 'owner', 'exec', 'audit'];
/** Roles the back end can give that no page of this front end is for yet (a tenant or network administrator). */
const NO_PAGES_YET: readonly string[] = ['tenant-admin', 'network-admin'];

const ID_TOKEN_MAX_LENGTH = 8192; // the back end refuses more (routes_auth.py)
const TOKEN_MAX_LENGTH = 4096;
const SUBJECT_MAX_LENGTH = 128;
// [ASSUMED] The longest a session may be told to last. The back end gives staff eight hours (DEC-523
// item 5); an answer of more than twelve is not one this side will believe.
const MAX_LIFETIME_MS = 12 * 3600_000;

export type StaffGrant = {
  /** The back end's bearer token. Opaque here: the session holds it and sends it, nothing reads it. */
  token: string;
  /** ISO 8601 instant, to the second: when the session must end, no later than the token. */
  expiresAt: string;
  role: Role;
  /** The back end's own derived subject (`stf-...`), read from the token it signed. Never the Entra object id. */
  sub: string;
};

export type StaffExchange = { kind: 'issued'; grant: StaffGrant } | { kind: 'refused' };

function isStaffRole(value: string): value is Role {
  return (STAFF_ROLES as readonly string[]).includes(value);
}

/**
 * Asks the back end for the person's token. `refused` is the back end's one answer for everyone it
 * will not sign in (a 403, whatever the cause: it says nothing more and neither does this). Any other
 * failure, or an answer that is not what the contract says, is a `SignInRefused` with a fixed reason,
 * so the person sees a failed sign-in and never the access message for a fault.
 */
export async function exchangeStaffToken(
  idToken: string,
  host: string | null,
  now: Date = new Date(),
): Promise<StaffExchange> {
  if (typeof idToken !== 'string' || idToken.length === 0 || idToken.length > ID_TOKEN_MAX_LENGTH) {
    throw new SignInRefused('bad-token');
  }
  let reply;
  try {
    reply = await callLinkApi({ method: 'POST', path: '/auth/token', host, body: { idToken } });
  } catch (error) {
    if (error instanceof LinkApiError) throw new SignInRefused('exchange-failed');
    throw error; // A missing back-end address is a set-up fault, named by its variable.
  }
  if (reply.status === 403) return { kind: 'refused' };
  if (reply.status !== 200) throw new SignInRefused('exchange-failed');

  const answer = reply.body;
  if (typeof answer !== 'object' || answer === null || Array.isArray(answer)) throw new SignInRefused('exchange-answer');
  const { token, expiresAt, role } = answer as Record<string, unknown>;
  if (typeof role !== 'string' || typeof token !== 'string' || typeof expiresAt !== 'string') {
    throw new SignInRefused('exchange-answer');
  }
  if (NO_PAGES_YET.includes(role)) return { kind: 'refused' };
  if (!isStaffRole(role)) throw new SignInRefused('exchange-answer');

  const claims = readToken(token);
  if (claims === null) throw new SignInRefused('exchange-answer');
  const ends = sessionEnd(expiresAt, claims.expiresAtMs, now);
  if (ends === null) throw new SignInRefused('exchange-answer');
  return { kind: 'issued', grant: { token, expiresAt: ends, role, sub: claims.sub } };
}

/**
 * When a session made from a token must end: the answer's expiry or the token's own, whichever is
 * first (a session never outlives its token), to the second. Null when that is not a future instant
 * within twelve hours, which is not an answer this side believes.
 */
export function sessionEnd(expiresAt: string, tokenExpiresAtMs: number, now: Date): string | null {
  const answered = Date.parse(expiresAt);
  if (Number.isNaN(answered)) return null;
  const ends = Math.floor(Math.min(answered, tokenExpiresAtMs) / 1000) * 1000;
  if (ends <= now.getTime() || ends - now.getTime() > MAX_LIFETIME_MS) return null;
  return new Date(ends).toISOString();
}

/**
 * The subject and expiry of a token our own back end signed, read without checking the signature: this
 * side cannot (it holds no key) and does not need to, because the token came over the server-to-server
 * call just made and is only ever sent back to the same back end, which checks it.
 */
export function readToken(token: string): { sub: string; expiresAtMs: number } | null {
  if (token.length === 0 || token.length > TOKEN_MAX_LENGTH || token.split('.').length !== 3) return null;
  try {
    const { sub, exp } = decodeJwt(token);
    if (typeof sub !== 'string' || sub.length === 0 || sub.length > SUBJECT_MAX_LENGTH) return null;
    if (typeof exp !== 'number' || !Number.isFinite(exp)) return null;
    return { sub, expiresAtMs: exp * 1000 };
  } catch {
    return null;
  }
}
