import { checkCsrf, clearCsrf } from '@/lib/auth/csrf';
import { destroySession, sessionFromRequest, type Role, type Session } from '@/lib/auth/session';
import { FhirError } from '@/lib/fhir/client';
import { renewIfDue } from '@/lib/reporter/renew';
import { toBffError } from './errors';
import { refusesTenantInput } from './inputGuard';

// Wraps a BFF route handler: session, role, CSRF and input checks first, then the handler, with any
// thrown error turned into a fixed-message response, and every answer made private and never stored.
//
// The tenant is the session's (the signed claim of the token the back end issued), and the session is
// read only on the host it was made on. A caller cannot name a tenant, a scope or a network in the
// query, a header or a body: such a request is refused before the handler runs (TEN-044).

export type BffOptions = {
  /** Roles that may call the route. Omit to allow any signed-in role. */
  roles?: Role[];
  /**
   * POST, PUT, PATCH and DELETE are always checked. Set true to check other
   * methods too. False cannot switch the check off for an unsafe method.
   */
  csrf?: boolean;
  /**
   * The route takes an id from the caller. A refusal from the back end is then always the one 404,
   * so an id that is in another tenant cannot be told from an id that is nowhere.
   */
  idScoped?: boolean;
};

export type BffHandler<C = unknown> = (
  request: Request,
  session: Session,
  context: C,
) => Response | Promise<Response>;

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function refuse(status: number, code: string): Response {
  return Response.json({ code }, { status });
}

// Directives that would let a cache keep, share or reuse an answer. They are taken away; the rest
// (`no-transform` on a stream) is kept.
const CACHING_DIRECTIVE = /^(public|private|no-store|max-age|s-maxage|stale-while-revalidate|stale-if-error|immutable|must-revalidate|proxy-revalidate)(=|$)/;
const VARY_ALWAYS = ['Cookie', 'Host'];

function privateNoStore(response: Response): Response {
  try {
    const headers = new Headers(response.headers);
    const kept = (headers.get('Cache-Control') ?? '')
      .split(',')
      .map((directive) => directive.trim().toLowerCase())
      .filter((directive) => directive !== '' && !CACHING_DIRECTIVE.test(directive));
    headers.set('Cache-Control', ['private', 'no-store', ...new Set(kept)].join(', '));

    const vary = (headers.get('Vary') ?? '').split(',').map((name) => name.trim()).filter((name) => name !== '');
    const have = new Set(vary.map((name) => name.toLowerCase()));
    for (const name of VARY_ALWAYS) if (!have.has(name.toLowerCase())) vary.push(name);
    headers.set('Vary', vary.join(', '));

    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  } catch {
    // A response that cannot be rebuilt is a fault, not a pass: a fixed answer, no body of its own.
    return new Response(null, { status: 500, headers: { 'Cache-Control': 'private, no-store', Vary: 'Cookie, Host' } });
  }
}

async function endSession(): Promise<void> {
  await destroySession();
  await clearCsrf();
}

export function withBff<C = unknown>(
  handler: BffHandler<C>,
  options: BffOptions = {},
): (request: Request, context: C) => Promise<Response> {
  async function run(request: Request, context: C): Promise<Response> {
    try {
      const session = await sessionFromRequest(request);
      if (!session) return refuse(401, 'no-session');

      if (options.roles && !options.roles.includes(session.role)) {
        return refuse(403, 'forbidden');
      }

      const check = UNSAFE_METHODS.has(request.method.toUpperCase()) || options.csrf === true;
      if (check && !checkCsrf(request, session)) return refuse(403, 'csrf');

      if (await refusesTenantInput(request)) return refuse(400, 'invalid');

      // A reporter's token lasts 30 minutes: it is renewed from the live PIN session when due (W8E,
      // DEC-792), after every check above so a refused request asks the back end for nothing. A session
      // that cannot be renewed has ended.
      let active = session;
      if (session.pinSession !== undefined) {
        const renewal = await renewIfDue(session);
        if (renewal.kind === 'ended') {
          await endSession();
          return Response.json({ code: 'session-ended', message: 'Please sign in again.' }, { status: 401 });
        }
        active = renewal.session;
      }

      return await handler(request, active, context);
    } catch (error) {
      // The back end no longer knows this session (expired, suspended, role changed): so do we.
      if (error instanceof FhirError && error.status === 401) {
        await endSession();
        return Response.json({ code: 'session-ended', message: 'Please sign in again.' }, { status: 401 });
      }
      return toBffError(error, { idScoped: options.idScoped });
    }
  }

  return async (request, context) => privateNoStore(await run(request, context));
}
