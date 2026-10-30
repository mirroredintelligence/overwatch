import { clearCsrf, CSRF_COOKIE, issueCsrf } from '@/lib/auth/csrf';
import { destroySession, readRequestCookie } from '@/lib/auth/session';
import { withBff } from '@/lib/bff/handler';

// The browser's view of its own session: display fields only. It never carries the back-end token,
// the subject or the tenant id: the tenant is the session's and nothing in the browser needs it.

const TOKEN_SHAPE = /^[A-Za-z0-9_-]{43}$/;

const get = withBff(async (request, session) => {
  // Keep the token already in the cookie, so a second tab is not logged out.
  const existing = readRequestCookie(request, CSRF_COOKIE);
  const csrfToken = existing && TOKEN_SHAPE.test(existing) ? existing : await issueCsrf();
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
