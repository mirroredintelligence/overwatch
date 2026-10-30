import { CSRF_COOKIE, issueCsrf, verifyCsrfToken } from '@/lib/auth/csrf';
import { requestHost } from '@/lib/auth/host';
import { readRequestCookie, sessionFromRequest } from '@/lib/auth/session';
import { preSessionSubject, refuse } from '@/lib/reporter/bff';
import { ensureDevice } from '@/lib/reporter/device';

// The reporter's first call on any phone (W33). It gives the page its CSRF token, reusing the
// cookie's token when there is one so two tabs agree, and makes sure the phone has its device id.
// It answers no tenant, no person and no device id: those never leave the cookies.
//
// Before sign-in the token is bound to this host and this phone. Once a reporter is signed in on this
// host, the writes they make are checked against the session (TEN-046, withBff), so the token given
// then is bound to the session: the phone's pre-session token never verifies for a session, and the
// two never mix. Only a reporter's session on this very host counts; any other (a staff session, a
// session of another host, an expired or damaged one) is as no session.

const NO_STORE = { 'Cache-Control': 'no-store' };

export async function GET(request: Request): Promise<Response> {
  // The token is bound to this host and this phone's device id (preSessionSubject), so the device
  // is made first, and a token planted for another host or phone is replaced, not kept.
  const host = requestHost(request);
  if (host === null) return refuse(400, 'invalid');
  const deviceId = await ensureDevice(request);
  const session = await sessionFromRequest(request);
  const subject = session !== null && session.role === 'reporter' ? session : preSessionSubject(host, deviceId);
  const existing = readRequestCookie(request, CSRF_COOKIE);
  const csrfToken = existing && verifyCsrfToken(subject, existing) ? existing : await issueCsrf(subject);
  return Response.json({ csrfToken }, { headers: NO_STORE });
}
