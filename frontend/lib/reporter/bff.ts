import { checkCsrf, type CsrfSubject } from '@/lib/auth/csrf';
import { requestHost } from '@/lib/auth/host';
import { toBffError } from '@/lib/bff/errors';
import { deviceIdFromRequest } from './device';

// Shared shape of the reporter's pre-session BFF routes (W33 to W55, W8E): a phone with no session
// yet. They answer from the back end, and never say a thing is valid when it has not been checked.

const NO_STORE = { 'Cache-Control': 'no-store' };
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export function refuse(status: number, code: string): Response {
  return Response.json({ code }, { status, headers: NO_STORE });
}

/**
 * What a CSRF token is bound to before anyone is signed in (TEN-046, F6A): the host the phone is
 * talking to and the phone's own device id. There is no tenant id to bind (the back end knows the
 * tenant from the host and the BFF has no signed claim yet), so the tenant part is empty, which no
 * session's tenant ever is: a token made for a signed-in session never verifies here, and a token made
 * here never verifies for a session. A token made for one host does not verify on another.
 */
export function preSessionSubject(host: string, deviceId: string): CsrfSubject {
  return { tenantId: '', host, sub: `device:${deviceId}` };
}

/** The subject of this request's CSRF token, or null when it has no host or its phone has no device id yet. */
export function preSessionSubjectOf(request: Request): CsrfSubject | null {
  const host = requestHost(request);
  const device = deviceIdFromRequest(request);
  return host === null || device === undefined ? null : preSessionSubject(host, device);
}

/**
 * A route that needs no session (the set-up steps, before a reporter is signed in). Unsafe methods
 * need the CSRF header, and its token must be the one issued to this phone on this host
 * (`GET /api/bff/reporter/start` issues it); any thrown error becomes the fixed-message response of
 * the BFF.
 */
export function preSession<C>(
  handler: (request: Request, context: C) => Response | Promise<Response>,
): (request: Request, context: C) => Promise<Response> {
  return async (request, context) => {
    try {
      if (UNSAFE.has(request.method.toUpperCase())) {
        const subject = preSessionSubjectOf(request);
        if (subject === null || !checkCsrf(request, subject)) return refuse(403, 'csrf');
      }
      return await handler(request, context);
    } catch (error) {
      return toBffError(error);
    }
  };
}
