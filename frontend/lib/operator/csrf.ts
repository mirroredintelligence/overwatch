import { createHash, createHmac, hkdfSync, timingSafeEqual } from 'node:crypto';
import { cookies } from 'next/headers';
import { baseCookieOptions, readRequestCookie, sessionSecretKey } from '@/lib/auth/session';

// Double-submit CSRF for the operator console (TEN-083), made as lib/auth/csrf.ts makes a tenant's: a
// random nonce and a MAC of the nonce and of the session it was issued for, as `<nonce>.<mac>`, in a cookie
// the page script can read and repeated in a header on every write. It has a cookie, a key and a material
// of its own, so a token issued to a tenant's person is never an operator's, even for the same subject and host.

export const OPERATOR_CSRF_COOKIE = 'diucs_op_csrf';
export const OPERATOR_CSRF_HEADER = 'X-CSRF-Token';

const NONCE_BYTES = 32;
const PART = /^[A-Za-z0-9_-]{43}$/;
const TOKEN = /^([A-Za-z0-9_-]{43})\.([A-Za-z0-9_-]{43})$/;

/** What a token is bound to: the console's host and the operator's account reference. */
export type OperatorCsrfSubject = { host: string; sub: string };

function macKey(): Uint8Array {
  return new Uint8Array(hkdfSync('sha256', sessionSecretKey(), 'diucs-operator-csrf', 'operator-csrf-token-v1', 32));
}

function macOf(subject: OperatorCsrfSubject, nonce: string): string {
  return createHmac('sha256', macKey()).update(['operator-csrf', subject.host, subject.sub, nonce].join('\n')).digest('base64url');
}

function digest(value: string): Buffer {
  return createHash('sha256').update(value).digest();
}

export function operatorCsrfTokenFor(subject: OperatorCsrfSubject, nonce: string): string {
  if (!PART.test(nonce)) throw new Error('The CSRF nonce is not 32 bytes of base64url');
  return `${nonce}.${macOf(subject, nonce)}`;
}

/** True only for a token made for this session. Constant-time. */
export function verifyOperatorCsrfToken(subject: OperatorCsrfSubject, token: unknown): boolean {
  macKey(); // a missing secret throws, it is not "no match"
  if (typeof token !== 'string') return false;
  const parts = TOKEN.exec(token);
  if (parts === null) return false;
  const [, nonce = '', mac = ''] = parts;
  return timingSafeEqual(digest(mac), digest(macOf(subject, nonce)));
}

export async function issueOperatorCsrf(subject: OperatorCsrfSubject): Promise<string> {
  const bytes = new Uint8Array(NONCE_BYTES);
  globalThis.crypto.getRandomValues(bytes);
  const token = operatorCsrfTokenFor(subject, Buffer.from(bytes).toString('base64url'));
  const store = await cookies();
  // Not HttpOnly: the page must read it to send the header.
  store.set(OPERATOR_CSRF_COOKIE, token, { ...baseCookieOptions(), httpOnly: false });
  return token;
}

export async function clearOperatorCsrf(): Promise<void> {
  const store = await cookies();
  store.set(OPERATOR_CSRF_COOKIE, '', { ...baseCookieOptions(), httpOnly: false, maxAge: 0 });
}

/** True only when the header equals the operator cookie AND the token is the one issued for this session. */
export function checkOperatorCsrf(request: Request, subject: OperatorCsrfSubject): boolean {
  const header = request.headers.get(OPERATOR_CSRF_HEADER);
  const cookie = readRequestCookie(request, OPERATOR_CSRF_COOKIE);
  const bound = verifyOperatorCsrfToken(subject, cookie);
  if (!header || !cookie) return false;
  return timingSafeEqual(digest(header), digest(cookie)) && bound;
}
