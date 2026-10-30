import { cookies, headers } from 'next/headers';
import { EncryptJWT, jwtDecrypt } from 'jose';
import { normaliseHost, requestHost } from './host';
import { isTenantId } from './ids';

// The BFF session: who the user is, the tenant they are signed into and the back-end token, sealed
// into one HTTP-only cookie. Encrypted (dir + A256GCM), so the browser can neither read nor change
// it. Nothing here logs a cookie value, a token or the secret.
//
// The tenant (DEC-130 item 3, DEC-134 item 3) is the one the back end issued the token for, read from
// the token the back end returned at sign-in and never from a request. The session is also tied to
// the HOST it was made on, and is read only on that host: the cookie is host-only, and this closes
// the case of a cookie set from a sibling sub-domain. A session with no tenant or no host is not a
// session (fail closed).

export const ROLES = [
  'reporter',
  'advisor',
  'clinical',
  'lead',
  'owner',
  'exec',
  'wall',
  'anonymous-link',
  'support',
  'audit',
  'tenant-admin',
  'network-admin',
] as const;

export type Role = (typeof ROLES)[number];

/** The roles a staff sign-in can give (the back end maps a directory group to one of these). */
export const STAFF_ROLES: readonly Role[] = [
  'advisor',
  'clinical',
  'lead',
  'owner',
  'exec',
  'audit',
  'tenant-admin',
  'network-admin',
];

export type Session = {
  role: Role;
  /** The tenant the back-end token is for. Never sent to the browser. */
  tenantId: string;
  /** The host the session was made on, in lower case, with its port when it has one. */
  host: string;
  services: string[];
  sub: string;
  device?: string;
  backendToken: string;
  /** ISO 8601 instant. At or after this instant the session is void. */
  expiresAt: string;
};

export const SESSION_COOKIE = 'diucs_session';

const SECRET_VARIABLE = 'SESSION_SECRET';
// 32 bytes in base64 are 43 characters and one '='.
const BASE64_32_BYTES = /^[A-Za-z0-9+/]{43}=$/;
const ENCRYPTION = { alg: 'dir', enc: 'A256GCM' } as const;

function secretKey(): Uint8Array {
  // Read at call time, so a missing value fails the request that needs it. The
  // message names the variable only, never its value.
  const value = process.env[SECRET_VARIABLE];
  if (!value || !BASE64_32_BYTES.test(value)) {
    throw new Error(`${SECRET_VARIABLE} must be set to 32 random bytes, base64 encoded`);
  }
  return new Uint8Array(Buffer.from(value, 'base64'));
}

/** Attributes shared by every cookie the BFF sets. */
export function baseCookieOptions() {
  return {
    sameSite: 'strict' as const,
    path: '/',
    // Secure everywhere except local development over http.
    secure: process.env.NODE_ENV !== 'development',
  };
}

function sessionCookieOptions() {
  return { ...baseCookieOptions(), httpOnly: true };
}

export async function sealSession(session: Session, now: Date = new Date()): Promise<string> {
  const expiresMs = Date.parse(session.expiresAt);
  if (Number.isNaN(expiresMs)) throw new Error('Session expiry is not a date');
  if (expiresMs <= now.getTime()) throw new Error('Session has already expired');
  if (!isTenantId(session.tenantId)) throw new Error('Session has no valid tenant');
  if (normaliseHost(session.host) !== session.host) throw new Error('Session has no valid host');

  const claims: Record<string, unknown> = {
    role: session.role,
    tenantId: session.tenantId,
    host: session.host,
    services: session.services,
    sub: session.sub,
    backendToken: session.backendToken,
    expiresAt: session.expiresAt,
  };
  if (session.device !== undefined) claims.device = session.device;

  return new EncryptJWT(claims)
    .setProtectedHeader(ENCRYPTION)
    .setIssuedAt(Math.floor(now.getTime() / 1000))
    .setExpirationTime(Math.floor(expiresMs / 1000))
    .encrypt(secretKey());
}

function isRole(value: unknown): value is Role {
  return typeof value === 'string' && (ROLES as readonly string[]).includes(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

/** Returns null for anything that is not a live session sealed with our key. */
export async function unsealSession(value: string, now: Date = new Date()): Promise<Session | null> {
  const key = secretKey(); // A missing secret is a fault, not "no session".
  if (!value) return null;
  try {
    const { payload } = await jwtDecrypt(value, key, {
      keyManagementAlgorithms: ['dir'],
      contentEncryptionAlgorithms: ['A256GCM'],
      currentDate: now,
    });
    const { role, tenantId, host, services, sub, device, backendToken, expiresAt } = payload;
    if (!isRole(role)) return null;
    if (!isTenantId(tenantId)) return null;
    if (typeof host !== 'string' || normaliseHost(host) !== host) return null;
    if (!Array.isArray(services) || !services.every((s) => typeof s === 'string')) return null;
    if (!nonEmptyString(sub) || !nonEmptyString(backendToken)) return null;
    if (device !== undefined && typeof device !== 'string') return null;
    if (typeof expiresAt !== 'string') return null;
    const expiresMs = Date.parse(expiresAt);
    if (Number.isNaN(expiresMs) || expiresMs <= now.getTime()) return null;

    const session: Session = { role, tenantId, host, services: [...services], sub, backendToken, expiresAt };
    if (device !== undefined) session.device = device;
    return session;
  } catch {
    return null;
  }
}

/** Value of one cookie in a request's Cookie header, matched by exact name. */
export function readRequestCookie(request: Request, name: string): string | undefined {
  const header = request.headers.get('cookie');
  if (!header) return undefined;
  for (const part of header.split(';')) {
    const at = part.indexOf('=');
    if (at < 0) continue;
    if (part.slice(0, at).trim() === name) return part.slice(at + 1).trim();
  }
  return undefined;
}

/** The session of a request, only when it is addressed to the host the session was made on. */
export async function sessionFromRequest(
  request: Request,
  now: Date = new Date(),
): Promise<Session | null> {
  const session = await unsealSession(readRequestCookie(request, SESSION_COOKIE) ?? '', now);
  if (session === null) return null;
  return session.host === requestHost(request) ? session : null;
}

/** For Server Components and route handlers that read the Next cookie store. */
export async function getSession(): Promise<Session | null> {
  const store = await cookies();
  const session = await unsealSession(store.get(SESSION_COOKIE)?.value ?? '');
  if (session === null) return null;
  const host = normaliseHost((await headers()).get('host'));
  return session.host === host ? session : null;
}

export async function createSession(session: Session): Promise<void> {
  const now = new Date();
  const sealed = await sealSession(session, now);
  const seconds = Math.floor((Date.parse(session.expiresAt) - now.getTime()) / 1000);
  const store = await cookies();
  store.set(SESSION_COOKIE, sealed, { ...sessionCookieOptions(), maxAge: seconds });
}

export async function destroySession(): Promise<void> {
  const store = await cookies();
  store.set(SESSION_COOKIE, '', { ...sessionCookieOptions(), maxAge: 0 });
}

/** The sealing key, for other BFF cookies that derive their own key from it (W09). */
export { secretKey as sessionSecretKey };
