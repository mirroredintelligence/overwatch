import { clearCsrf, CSRF_COOKIE, issueCsrf, verifyCsrfToken } from '@/lib/auth/csrf';
import { destroySession, readRequestCookie } from '@/lib/auth/session';
import { withBff } from '@/lib/bff/handler';

// The browser's view of its own session: display fields only. It never carries the back-end token,
// the subject or the tenant id: the tenant is the session's and nothing in the browser needs it.

const get = withBff(async (request, session) => {
  // Keep the token already in the cookie when it is this session's, so a second tab is not logged
  // out; one that is not (a stale or another session's) is replaced.
  const existing = readRequestCookie(request, CSRF_COOKIE);
  const csrfToken = existing && verifyCsrfToken(session, existing) ? existing : await issueCsrf(session);
  return Response.json({ role: session.role, services: session.services, csrfToken });
});

const del = withBff(
  async () => {
    await destroySession();
    await clearCsrf();
    return new Response(null, { status: 204 });
  },
  { csrf: true },
);

// Route handlers receive a context the session routes do not use.
export const GET = (request: Request) => get(request, undefined);
export const DELETE = (request: Request) => del(request, undefined);
