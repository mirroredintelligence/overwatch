import { checkCsrf, type CsrfSubject } from '@/lib/auth/csrf';
import { requestHost } from '@/lib/auth/host';
import type { Session } from '@/lib/auth/session';
import { toBffError } from '@/lib/bff/errors';
import { deviceIdFromRequest } from './device';

// Shared shape of the reporter BFF routes (W33 to W55). A route either answers from the back end
// or, where the back end has no route for it yet, answers `not-built` (503). It never answers with
// a made-up value, and it never says a thing is valid when it has not been checked.

const NO_STORE = { 'Cache-Control': 'no-store' };
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export const NOT_BUILT = { code: 'not-built', message: 'This is not available yet.' } as const;

export function notBuilt(): Response {
  return Response.json(NOT_BUILT, { status: 503, headers: NO_STORE });
}

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

/**
 * The 404 a service the caller does not act for gets, the same as an unknown service (W35). Null
 * when the service is the caller's own, so the route goes on.
 */
export function ownService(session: Session, serviceId: string): Response | null {
  return session.services.includes(serviceId) ? null : refuse(404, 'not-found');
}
