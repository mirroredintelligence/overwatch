import { hkdfSync } from 'node:crypto';
import { cookies, headers } from 'next/headers';
import { EncryptJWT, jwtDecrypt } from 'jose';
import { normaliseHost, requestHost } from '@/lib/auth/host';
import { baseCookieOptions, readRequestCookie, sessionSecretKey } from '@/lib/auth/session';

// The operator console's session (TEN-083, DEC-1000, DEC-1005): who is signed in to the platform console,
// the role the operator's own directory gave, and the back end's operator token, sealed into one HTTP-only
// cookie. It is a different KIND of session from a tenant's (lib/auth/session.ts) and the two never mix:
//
//   - it has NO tenant: an operator's token names none and the back end takes the tenant of an act from
//     the path of the call, after it has checked the token and the role;
//   - its cookie has another name (`diucs_operator`) and is sealed with a key derived from the session
//     secret for this one purpose, so a tenant's sealed session is not an operator's and the other way
//     round, even if a cookie is renamed;
//   - an unsealed payload that carries a tenant, another kind or a role that is not an operator's is not
//     a session, even when it opens (fail closed);
//   - like a tenant's, it is read only on the host it was made on (the console has a host of its own).
//
// Nothing here logs a cookie value, a token or the secret.

export const OPERATOR_ROLES = ['platform-operator', 'support'] as const;
export type OperatorRole = (typeof OPERATOR_ROLES)[number];

export type OperatorSession = {
  role: OperatorRole;
  /** The host the session was made on, in lower case, with its port when it has one. */
  host: string;
  /** The opaque account reference the back end derived for the operator (never a name or an object id). */
  accountRef: string;
  /** The back end's operator token (audience `diucs-ops`). Opaque here: sent to `/platform` and nowhere else. */
  backendToken: string;
  /** ISO 8601 instant. At or after this instant the session is void; never later than the token. */
  expiresAt: string;
};

export const OPERATOR_COOKIE = 'diucs_operator';
const KIND = 'operator';
const ENCRYPTION = { alg: 'dir', enc: 'A256GCM' } as const;

export function isOperatorRole(value: unknown): value is OperatorRole {
  return typeof value === 'string' && (OPERATOR_ROLES as readonly string[]).includes(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

/** The sealing key of an operator session: derived from the session secret, for this purpose only. */
export async function operatorSealingKey(): Promise<Uint8Array> {
  return new Uint8Array(hkdfSync('sha256', await sessionSecretKey(), 'diucs-operator-session', 'operator-session-v1', 32));
}

export async function sealOperatorSession(session: OperatorSession, now: Date = new Date()): Promise<string> {
  // A session that holds anything but its five fields is not an operator session (no tenant, no extras).
  const extra = Object.keys(session).filter((key) => !['role', 'host', 'accountRef', 'backendToken', 'expiresAt'].includes(key));
  if (extra.length > 0) throw new Error('Operator session has a field it must not have');
  if (!isOperatorRole(session.role)) throw new Error('Operator session has no operator role');
  const expiresMs = Date.parse(session.expiresAt);
  if (Number.isNaN(expiresMs)) throw new Error('Session expiry is not a date');
  if (expiresMs <= now.getTime()) throw new Error('Session has already expired');
  if (normaliseHost(session.host) !== session.host) throw new Error('Session has no valid host');
  if (!nonEmptyString(session.accountRef) || !nonEmptyString(session.backendToken)) throw new Error('Session has no account or token');

  return new EncryptJWT({
    kind: KIND,
    role: session.role,
    host: session.host,
    accountRef: session.accountRef,
    backendToken: session.backendToken,
    expiresAt: session.expiresAt,
  })
    .setProtectedHeader(ENCRYPTION)
    .setIssuedAt(Math.floor(now.getTime() / 1000))
    .setExpirationTime(Math.floor(expiresMs / 1000))
    .encrypt(await operatorSealingKey());
}

/** Returns null for anything that is not a live operator session sealed with our key. */
export async function unsealOperatorSession(value: string, now: Date = new Date()): Promise<OperatorSession | null> {
  const key = await operatorSealingKey(); // A missing secret is a fault, not "no session".
  if (!value) return null;
  try {
    const { payload } = await jwtDecrypt(value, key, {
      keyManagementAlgorithms: ['dir'],
      contentEncryptionAlgorithms: ['A256GCM'],
      currentDate: now,
    });
    // A tenant has no place in an operator session, under any of the names a tenant goes by.
    if ('tenantId' in payload || 'tenant' in payload || 'services' in payload || 'epoch' in payload) return null;
    const { kind, role, host, accountRef, backendToken, expiresAt } = payload;
    if (kind !== KIND || !isOperatorRole(role)) return null;
    if (typeof host !== 'string' || normaliseHost(host) !== host) return null;
    if (!nonEmptyString(accountRef) || !nonEmptyString(backendToken) || typeof expiresAt !== 'string') return null;
    const expiresMs = Date.parse(expiresAt);
    if (Number.isNaN(expiresMs) || expiresMs <= now.getTime()) return null;
    return { role, host, accountRef, backendToken, expiresAt };
  } catch {
    return null;
  }
}

/** The operator session of a request, only when it is addressed to the host the session was made on. */
export async function operatorSessionFromRequest(request: Request, now: Date = new Date()): Promise<OperatorSession | null> {
  const session = await unsealOperatorSession(readRequestCookie(request, OPERATOR_COOKIE) ?? '', now);
  if (session === null) return null;
  return session.host === requestHost(request) ? session : null;
}

/** For Server Components and route handlers that read the Next cookie store. */
export async function getOperatorSession(): Promise<OperatorSession | null> {
  const store = await cookies();
  const session = await unsealOperatorSession(store.get(OPERATOR_COOKIE)?.value ?? '');
  if (session === null) return null;
  const host = normaliseHost((await headers()).get('host'));
  return session.host === host ? session : null;
}

export async function createOperatorSession(session: OperatorSession): Promise<void> {
  const now = new Date();
  const sealed = await sealOperatorSession(session, now);
  const seconds = Math.floor((Date.parse(session.expiresAt) - now.getTime()) / 1000);
  const store = await cookies();
  store.set(OPERATOR_COOKIE, sealed, { ...baseCookieOptions(), httpOnly: true, maxAge: seconds });
}

export async function destroyOperatorSession(): Promise<void> {
  const store = await cookies();
  store.set(OPERATOR_COOKIE, '', { ...baseCookieOptions(), httpOnly: true, maxAge: 0 });
}
