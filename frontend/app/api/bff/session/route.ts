import { clearCsrf, CSRF_COOKIE, issueCsrf } from '@/lib/auth/csrf';
import { destroySession, readRequestCookie } from '@/lib/auth/session';
import { withBff } from '@/lib/bff/handler';

// The browser's view of its own session. It never carries the back-end token.

const NO_STORE = { 'Cache-Control': 'no-store' };
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{43}$/;

const get = withBff(async (request, session) => {
  // Keep the token already in the cookie, so a second tab is not logged out.
  const existing = readRequestCookie(request, CSRF_COOKIE);
  const csrfToken = existing && TOKEN_SHAPE.test(existing) ? existing : await issueCsrf();
  return Response.json(
    { role: session.role, services: session.services, sub: session.sub, csrfToken },
    { headers: NO_STORE },
  );
});

const del = withBff(
  async () => {
    await destroySession();
    await clearCsrf();
    return new Response(null, { status: 204, headers: NO_STORE });
  },
  { csrf: true },
);

// Route handlers receive a context the session routes do not use.
export const GET = (request: Request) => get(request, undefined);
export const DELETE = (request: Request) => del(request, undefined);
