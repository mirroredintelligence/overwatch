import { privateNoStore, refuse } from '@/lib/bff/handler';
import { toBffError } from '@/lib/bff/errors';
import { refusesTenantInput } from '@/lib/bff/inputGuard';
import { FhirError } from '@/lib/fhir/client';
import { checkOperatorCsrf, clearOperatorCsrf } from './csrf';
import { destroyOperatorSession, operatorSessionFromRequest, type OperatorRole, type OperatorSession } from './session';

// Wraps an operator console BFF route handler (TEN-083), as `withBff` wraps a tenant's person's: the
// operator's session, its role, CSRF and the input guard first, then the handler, with any thrown error
// turned into a fixed-message response, and every answer made private and never stored.
//
// It reads the OPERATOR session and nothing else: a tenant's session, of any role, is no session here, and
// an operator session is none for `withBff`. The tenant of an act on a tenant is named by the path of the
// back-end call the handler makes (`/platform/tenants/{id}/...`), after the back end has checked the token
// and the role; a caller cannot name a tenant, a scope or a network in the query, a header or a body of this
// BFF's own request (the input guard, TEN-044), and the path ids a handler takes are checked by shape.

export type OperatorBffOptions = {
  /** Operator roles that may call the route. Omit to allow both. */
  roles?: OperatorRole[];
  /** POST, PUT, PATCH and DELETE are always checked. Set true to check other methods too. */
  csrf?: boolean;
  /** The route takes an id from the caller: a refusal from the back end is then always the one 404. */
  idScoped?: boolean;
};

export type OperatorBffHandler<C = unknown> = (request: Request, session: OperatorSession, context: C) => Response | Promise<Response>;

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

async function endSession(): Promise<void> {
  await destroyOperatorSession();
  await clearOperatorCsrf();
}

export function withOperatorBff<C = unknown>(
  handler: OperatorBffHandler<C>,
  options: OperatorBffOptions = {},
): (request: Request, context: C) => Promise<Response> {
  async function run(request: Request, context: C): Promise<Response> {
    try {
      const session = await operatorSessionFromRequest(request);
      if (!session) return refuse(401, 'no-session');

      if (options.roles && !options.roles.includes(session.role)) return refuse(403, 'forbidden');

      const check = UNSAFE_METHODS.has(request.method.toUpperCase()) || options.csrf === true;
      if (check && !checkOperatorCsrf(request, { host: session.host, sub: session.accountRef })) return refuse(403, 'csrf');

      if (await refusesTenantInput(request)) return refuse(400, 'invalid');

      return await handler(request, session, context);
    } catch (error) {
      // The back end no longer knows this token (expired, the account stopped): so do we.
      if (error instanceof FhirError && error.status === 401) {
        await endSession();
        return Response.json({ code: 'session-ended', message: 'Please sign in again.' }, { status: 401 });
      }
      return toBffError(error, { idScoped: options.idScoped });
    }
  }

  return async (request, context) => privateNoStore(await run(request, context));
}
