import { createHash, timingSafeEqual } from 'node:crypto';
import { cookies } from 'next/headers';
import { baseCookieOptions, readRequestCookie } from '@/lib/auth/session';

// The link page's double-submit CSRF (DEC-167 item 3). The browser's own copy of the link's
// CSRF token is a cookie that only this link's BFF path receives, and the page sends the same
// value in X-CSRF-Token. The back end then checks that value against the link itself, so a
// forged post needs both the cookie and the token of this link. The cookie is HttpOnly: the
// page gets its copy from the BFF's JSON answer, never from script reading a cookie.

export const LINK_CSRF_COOKIE = 'diucs_link_csrf';
const MAX_AGE_SECONDS = 60 * 60;

export function linkCsrfPath(token: string): string {
  return `/api/bff/links/${token}`;
}

export async function issueLinkCsrf(token: string, value: string): Promise<void> {
  const store = await cookies();
  store.set(LINK_CSRF_COOKIE, value, {
    ...baseCookieOptions(),
    httpOnly: true,
    path: linkCsrfPath(token),
    maxAge: MAX_AGE_SECONDS,
  });
}

function digest(value: string): Buffer {
  return createHash('sha256').update(value).digest();
}

/** True only when the request is for this link's path and its header equals its cookie. Constant-time. */
export function checkLinkCsrf(request: Request, token: string): boolean {
  if (new URL(request.url).pathname !== linkCsrfPath(token)) return false;
  const header = request.headers.get('X-CSRF-Token');
  const cookie = readRequestCookie(request, LINK_CSRF_COOKIE);
  if (!header || !cookie) return false;
  // Hashing gives equal-length inputs, so the comparison never branches on length.
  return timingSafeEqual(digest(header), digest(cookie));
}
