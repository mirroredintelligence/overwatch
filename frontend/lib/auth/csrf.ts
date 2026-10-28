import { createHash, timingSafeEqual } from 'node:crypto';
import { cookies } from 'next/headers';
import { baseCookieOptions, readRequestCookie } from './session';

// Double-submit CSRF. The token is in a cookie the page script can read; every
// state-changing request must repeat it in a header. A forged cross-site
// request cannot read the cookie, so it cannot set the header.

export const CSRF_COOKIE = 'diucs_csrf';
export const CSRF_HEADER = 'X-CSRF-Token';

const TOKEN_BYTES = 32;

export async function issueCsrf(): Promise<string> {
  const bytes = new Uint8Array(TOKEN_BYTES);
  globalThis.crypto.getRandomValues(bytes);
  const token = Buffer.from(bytes).toString('base64url');
  const store = await cookies();
  // Not HttpOnly: the page must read it to send the header.
  store.set(CSRF_COOKIE, token, { ...baseCookieOptions(), httpOnly: false });
  return token;
}

export async function clearCsrf(): Promise<void> {
  const store = await cookies();
  store.set(CSRF_COOKIE, '', { ...baseCookieOptions(), httpOnly: false, maxAge: 0 });
}

function digest(value: string): Buffer {
  return createHash('sha256').update(value).digest();
}

/** True only when the header equals the cookie. Constant-time. */
export function checkCsrf(request: Request): boolean {
  const header = request.headers.get(CSRF_HEADER);
  const cookie = readRequestCookie(request, CSRF_COOKIE);
  if (!header || !cookie) return false;
  // Hashing gives equal-length inputs, so the comparison never branches on length.
  return timingSafeEqual(digest(header), digest(cookie));
}
