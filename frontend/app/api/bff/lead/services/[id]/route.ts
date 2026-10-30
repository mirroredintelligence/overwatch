import { withBff } from '@/lib/bff/handler';
import { fhirFetch, FhirError } from '@/lib/fhir/client';
import { routeId } from '@/lib/lead/bffInput';

// One service for the lead's service pages (W42): its name, and its suspension: whether it is suspended, since
// when, how many open requests the suspension expired, and the register number to phone (the back end's read,
// W7B C). Lead only. A service the back end does not know is a 404, with no detail. A malformed answer is a 500,
// never a guess.

type Context = { params: Promise<Record<string, string>> };

type Suspension = {
  suspended?: unknown;
  since?: unknown;
  expiredRequests?: unknown;
  registerNumber?: unknown;
};

const get = withBff<Context>(
  async (_request, session, context) => {
    const id = await routeId(context, 'id');
    const path = encodeURIComponent(id);
    const [{ data: service }, { data: suspension }] = await Promise.all([
      fhirFetch<{ name?: unknown }>(`/HealthcareService/${path}`, { token: session.backendToken, cache: 'no-store' }),
      fhirFetch<Suspension>(`/lead/services/${path}/suspension`, { root: true, token: session.backendToken, cache: 'no-store' }),
    ]);
    if (typeof service?.name !== 'string' || typeof suspension?.suspended !== 'boolean') {
      throw new FhirError(502, {
        resourceType: 'OperationOutcome',
        issue: [{ severity: 'error', code: 'exception', diagnostics: 'The back end returned an unreadable service.' }],
      });
    }
    const since = typeof suspension.since === 'string' ? suspension.since : null;
    const expired = typeof suspension.expiredRequests === 'number' ? suspension.expiredRequests : null;
    const register = typeof suspension.registerNumber === 'string' ? suspension.registerNumber : null;
    const body = suspension.suspended
      ? { name: service.name, suspended: true, since, expiredRequests: expired, registerPhone: register }
      : { name: service.name, suspended: false, registerPhone: register };
    return Response.json(body, { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
