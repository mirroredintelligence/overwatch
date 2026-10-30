import { CSRF_COOKIE, issueCsrf, verifyCsrfToken } from '@/lib/auth/csrf';
import { requestHost } from '@/lib/auth/host';
import { readRequestCookie } from '@/lib/auth/session';
import { preSessionSubject, refuse } from '@/lib/reporter/bff';
import { ensureDevice } from '@/lib/reporter/device';

// The reporter's first call on any phone (W33). It gives the page its CSRF token, reusing the
// cookie's token when there is one so two tabs agree, and makes sure the phone has its device id.
// It answers no tenant, no person and no device id: those never leave the cookies.

const NO_STORE = { 'Cache-Control': 'no-store' };

export async function GET(request: Request): Promise<Response> {
  // The token is bound to this host and this phone's device id (preSessionSubject), so the device
  // is made first, and a token planted for another host or phone is replaced, not kept.
  const host = requestHost(request);
  if (host === null) return refuse(400, 'invalid');
  const deviceId = await ensureDevice(request);
  const subject = preSessionSubject(host, deviceId);
  const existing = readRequestCookie(request, CSRF_COOKIE);
  const csrfToken = existing && verifyCsrfToken(subject, existing) ? existing : await issueCsrf(subject);
  return Response.json({ csrfToken }, { headers: NO_STORE });
}
