import { createHash, createHmac, timingSafeEqual } from 'node:crypto';
import { cookies } from 'next/headers';
import { baseCookieOptions, readRequestCookie, sessionSecretKey } from '@/lib/auth/session';

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

/**
 * The CSRF token of a renewal (KI-178). A closed link has no back-end token to answer with, so the BFF
 * makes one from the link and its own secret: the page reads it from the closed link's answer (a page of
 * another origin cannot read it) and sends it back in X-CSRF-Token. Nothing is stored. It is not the
 * token that answers a capacity link, and it says nothing of whether the link exists: every closed or
 * unknown link gets one. Throws when there is no secret to make it with.
 */
export function renewCsrfFor(token: string): string {
  return createHmac('sha256', Buffer.from(sessionSecretKey())).update(`link-renew:${token}`).digest('hex');
}

/** True only when the request is a renewal of this link and its header is this link's renewal token. */
export function checkRenewCsrf(request: Request, token: string): boolean {
  if (new URL(request.url).pathname !== `${linkCsrfPath(token)}/renew`) return false;
  const header = request.headers.get('X-CSRF-Token');
  if (!header) return false;
  let expected: string;
  try {
    expected = renewCsrfFor(token);
  } catch {
    return false; // no secret to check it with: refused, never allowed
  }
  return timingSafeEqual(digest(header), digest(expected));
}
