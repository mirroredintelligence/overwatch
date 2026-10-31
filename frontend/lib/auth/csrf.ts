import { createHash, createHmac, hkdfSync, timingSafeEqual } from 'node:crypto';
import { cookies } from 'next/headers';
import { baseCookieOptions, readRequestCookie, sessionSecretKey, type Session } from './session';

// Double-submit CSRF, bound to the session (TEN-046, audit D 3.6). The token is a random nonce and a
// MAC of the nonce and of the session it was issued for (the person, the tenant and the host), as
// `<nonce>.<mac>`. It is in a cookie the page script can read; every
// state-changing request must repeat it in a header. A forged cross-site request cannot read the
// cookie, so it cannot set the header; and a script on a sibling sub-domain that can plant a cookie
// still cannot make a token that verifies for this session, so a planted matching pair fails. A token
// issued for tenant A's session does not verify in tenant B's, and one issued to one person does not
// verify for another. (It is not tied to the life of one sign-in: it proves who and where, and the
// cookie that carries it is the person's own.)
//
// The link page has its own cookie, name, path and check (lib/links/csrf.ts): opening a link never
// touches this cookie.

export const CSRF_COOKIE = 'diucs_csrf';
export const CSRF_HEADER = 'X-CSRF-Token';

const NONCE_BYTES = 32;
const PART = /^[A-Za-z0-9_-]{43}$/;
const TOKEN = /^([A-Za-z0-9_-]{43})\.([A-Za-z0-9_-]{43})$/;

/** What a token is bound to. */
export type CsrfSubject = Pick<Session, 'tenantId' | 'host' | 'sub'>;

// The MAC key is derived from the session secret for this one purpose, so a sealed session or a
// sign-in transaction can never be passed off as a CSRF MAC. Read at call time: a missing secret is a
// fault (an error, so a 500), never a pass.
async function macKey(): Promise<Uint8Array> {
  return new Uint8Array(hkdfSync('sha256', await sessionSecretKey(), 'diucs-csrf', 'csrf-token-v1', 32));
}

async function macOf(subject: CsrfSubject, nonce: string): Promise<string> {
  const material = ['csrf', subject.tenantId, subject.host, subject.sub, nonce].join('\n');
  return createHmac('sha256', await macKey()).update(material).digest('base64url');
}

function digest(value: string): Buffer {
  return createHash('sha256').update(value).digest();
}

/** The token for a session and a nonce (32 random bytes, base64url). `issueCsrf` supplies the nonce; the key comes from the vault. */
export async function csrfTokenFor(subject: CsrfSubject, nonce: string): Promise<string> {
  if (!PART.test(nonce)) throw new Error('The CSRF nonce is not 32 bytes of base64url');
  return `${nonce}.${await macOf(subject, nonce)}`;
}

/** True only for a token made for this session. Constant-time. */
export async function verifyCsrfToken(subject: CsrfSubject, token: unknown): Promise<boolean> {
  const key = await macKey(); // a missing secret throws, it is not "no match"
  void key;
  if (typeof token !== 'string') return false;
  const parts = TOKEN.exec(token);
  if (parts === null) return false;
  const [, nonce = '', mac = ''] = parts;
  // Hashing gives equal-length inputs, so the comparison never branches on length.
  return timingSafeEqual(digest(mac), digest(await macOf(subject, nonce)));
}

export async function issueCsrf(subject: CsrfSubject): Promise<string> {
  const bytes = new Uint8Array(NONCE_BYTES);
  globalThis.crypto.getRandomValues(bytes);
  const token = await csrfTokenFor(subject, Buffer.from(bytes).toString('base64url'));
  const store = await cookies();
  // Not HttpOnly: the page must read it to send the header.
  store.set(CSRF_COOKIE, token, { ...baseCookieOptions(), httpOnly: false });
  return token;
}

export async function clearCsrf(): Promise<void> {
  const store = await cookies();
  store.set(CSRF_COOKIE, '', { ...baseCookieOptions(), httpOnly: false, maxAge: 0 });
}

/**
 * True only when the header equals the cookie AND the token is the one issued for this session.
 * Constant-time.
 */
export async function checkCsrf(request: Request, subject: CsrfSubject): Promise<boolean> {
  const header = request.headers.get(CSRF_HEADER);
  const cookie = readRequestCookie(request, CSRF_COOKIE);
  const bound = await verifyCsrfToken(subject, cookie);
  if (!header || !cookie) return false;
  // Hashing gives equal-length inputs, so the comparison never branches on length.
  const same = timingSafeEqual(digest(header), digest(cookie));
  return same && bound;
}
