import { fhirFetch } from '@/lib/fhir/client';
import { withOperatorBff } from '@/lib/operator/bff';
import { clearOperatorCsrf, issueOperatorCsrf, OPERATOR_CSRF_COOKIE, verifyOperatorCsrfToken } from '@/lib/operator/csrf';
import { destroyOperatorSession } from '@/lib/operator/session';
import { parsePlatformSession } from '@/lib/operator/session-view';
import { readRequestCookie } from '@/lib/auth/session';

// The console's view of its own session (TEN-083, DEC-1005): who is signed in, what the role may do and
// when the session ends, read from the back end (`GET /platform/session`), and the CSRF token the console
// sends on every write. Never the back-end token, a tenant or the sealed session.

const get = withOperatorBff(async (request, session) => {
  const { data } = await fhirFetch<unknown>('/platform/session', { root: true, token: session.backendToken, cache: 'no-store' });
  const view = parsePlatformSession(data);
  // Keep the token already in the cookie when it is this session's, so a second tab is not logged out.
  const subject = { host: session.host, sub: session.accountRef };
  const existing = readRequestCookie(request, OPERATOR_CSRF_COOKIE);
  const csrfToken = existing && (await verifyOperatorCsrfToken(subject, existing)) ? existing : await issueOperatorCsrf(subject);
  return Response.json({ role: view.role, accountRef: view.accountRef, expiresAt: view.expiresAt, permissions: view.permissions, csrfToken });
});

// For the browsers that act on it (Chromium; the page clears its own state too).
const CLEAR_SITE_DATA = '"cache", "storage"';

const del = withOperatorBff(
  async () => {
    await destroyOperatorSession();
    await clearOperatorCsrf();
    return new Response(null, { status: 204, headers: { 'Clear-Site-Data': CLEAR_SITE_DATA } });
  },
  { csrf: true },
);

export const GET = (request: Request) => get(request, undefined);
export const DELETE = (request: Request) => del(request, undefined);
