import { cookies } from 'next/headers';
import { EncryptJWT, jwtDecrypt } from 'jose';

// The BFF session: who the user is and the back-end token, sealed into one
// HTTP-only cookie. Encrypted (dir + A256GCM), so the browser can neither read
// nor change it. Nothing here logs a cookie value, a token or the secret.

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
] as const;

export type Role = (typeof ROLES)[number];

export type Session = {
  role: Role;
  services: string[];
  sub: string;
  device?: string;
  backendToken: string;
  /** ISO 8601 instant. At or after this instant the session is void. */
  expiresAt: string;
};

export const SESSION_COOKIE = 'diucs_session';

const SECRET_VARIABLE = 'SESSION_SECRET';
const KEY_BYTES = 32;
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
  const key = new Uint8Array(Buffer.from(value, 'base64'));
  if (key.length !== KEY_BYTES) {
    throw new Error(`${SECRET_VARIABLE} must be set to 32 random bytes, base64 encoded`);
  }
  return key;
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

  const claims: Record<string, unknown> = {
    role: session.role,
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
    const { role, services, sub, device, backendToken, expiresAt } = payload;
    if (!isRole(role)) return null;
    if (!Array.isArray(services) || !services.every((s) => typeof s === 'string')) return null;
    if (!nonEmptyString(sub) || !nonEmptyString(backendToken)) return null;
    if (device !== undefined && typeof device !== 'string') return null;
    if (typeof expiresAt !== 'string') return null;
    const expiresMs = Date.parse(expiresAt);
    if (Number.isNaN(expiresMs) || expiresMs <= now.getTime()) return null;

    const session: Session = { role, services: [...services], sub, backendToken, expiresAt };
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

export async function sessionFromRequest(
  request: Request,
  now: Date = new Date(),
): Promise<Session | null> {
  return unsealSession(readRequestCookie(request, SESSION_COOKIE) ?? '', now);
}

/** For Server Components and route handlers that read the Next cookie store. */
export async function getSession(): Promise<Session | null> {
  const store = await cookies();
  return unsealSession(store.get(SESSION_COOKIE)?.value ?? '');
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
