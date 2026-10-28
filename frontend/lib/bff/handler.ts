import { checkCsrf } from '@/lib/auth/csrf';
import { sessionFromRequest, type Role, type Session } from '@/lib/auth/session';
import { toBffError } from './errors';

// Wraps a BFF route handler: session, role and CSRF checks first, then the
// handler, with any thrown error turned into a fixed-message response.

export type BffOptions = {
  /** Roles that may call the route. Omit to allow any signed-in role. */
  roles?: Role[];
  /**
   * POST, PUT, PATCH and DELETE are always checked. Set true to check other
   * methods too. False cannot switch the check off for an unsafe method.
   */
  csrf?: boolean;
};

export type BffHandler<C = unknown> = (
  request: Request,
  session: Session,
  context: C,
) => Response | Promise<Response>;

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function refuse(status: number, code: string): Response {
  return Response.json({ code }, { status, headers: { 'Cache-Control': 'no-store' } });
}

export function withBff<C = unknown>(
  handler: BffHandler<C>,
  options: BffOptions = {},
): (request: Request, context: C) => Promise<Response> {
  return async (request, context) => {
    try {
      const session = await sessionFromRequest(request);
      if (!session) return refuse(401, 'no-session');

      if (options.roles && !options.roles.includes(session.role)) {
        return refuse(403, 'forbidden');
      }

      const check = UNSAFE_METHODS.has(request.method.toUpperCase()) || options.csrf === true;
      if (check && !checkCsrf(request)) return refuse(403, 'csrf');

      return await handler(request, session, context);
    } catch (error) {
      return toBffError(error);
    }
  };
}
