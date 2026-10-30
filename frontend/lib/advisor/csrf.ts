// The browser's copy of the session's CSRF token (W20). The page sends it in X-CSRF-Token with every
// state-changing BFF request; the BFF checks it against the cookie. Read here, never stored.

export const CSRF_COOKIE_NAME = 'diucs_csrf';

export function readCsrfCookie(): string | null {
  if (typeof document === 'undefined') return null;
  for (const part of document.cookie.split(';')) {
    const [name, ...rest] = part.trim().split('=');
    if (name === CSRF_COOKIE_NAME && rest.length > 0) return rest.join('=');
  }
  return null;
}
