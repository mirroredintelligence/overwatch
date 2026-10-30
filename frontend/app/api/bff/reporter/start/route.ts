import { CSRF_COOKIE, issueCsrf } from '@/lib/auth/csrf';
import { readRequestCookie } from '@/lib/auth/session';
import { ensureDevice } from '@/lib/reporter/device';

// The reporter's first call on any phone (W33). It gives the page its CSRF token, reusing the
// cookie's token when there is one so two tabs agree, and makes sure the phone has its device id.
// It answers no tenant, no person and no device id: those never leave the cookies.

const NO_STORE = { 'Cache-Control': 'no-store' };
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{43}$/;

export async function GET(request: Request): Promise<Response> {
  const existing = readRequestCookie(request, CSRF_COOKIE);
  const csrfToken = existing && TOKEN_SHAPE.test(existing) ? existing : await issueCsrf();
  await ensureDevice(request);
  return Response.json({ csrfToken }, { headers: NO_STORE });
}
