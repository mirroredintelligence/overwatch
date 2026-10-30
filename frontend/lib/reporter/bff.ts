import { checkCsrf } from '@/lib/auth/csrf';
import { toBffError } from '@/lib/bff/errors';

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
 * A route that needs no session (the set-up steps, before a reporter is signed in). Unsafe methods
 * need the CSRF header, and any thrown error becomes the fixed-message response of the BFF.
 */
export function preSession<C>(
  handler: (request: Request, context: C) => Response | Promise<Response>,
): (request: Request, context: C) => Promise<Response> {
  return async (request, context) => {
    try {
      if (UNSAFE.has(request.method.toUpperCase()) && !checkCsrf(request)) return refuse(403, 'csrf');
      return await handler(request, context);
    } catch (error) {
      return toBffError(error);
    }
  };
}
