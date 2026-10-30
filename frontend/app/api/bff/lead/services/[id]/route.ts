import { withBff } from '@/lib/bff/handler';
import { fhirFetch, FhirError } from '@/lib/fhir/client';
import { routeId } from '@/lib/lead/bffInput';

// One service's name, for the lead's service pages (W42). Lead only. The back end's service read carries no
// suspension state (its "active" is the registration, not the suspension, DEC-657), so this answers the name
// only; a suspension is shown from the suspend answer on the page.

type Context = { params: Promise<Record<string, string>> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const id = await routeId(context, 'id');
    const { data } = await fhirFetch<{ name?: unknown }>(`/HealthcareService/${encodeURIComponent(id)}`, {
      token: session.backendToken,
    });
    if (typeof data?.name !== 'string') {
      throw new FhirError(502, {
        resourceType: 'OperationOutcome',
        issue: [{ severity: 'error', code: 'exception', diagnostics: 'The back end returned a service with no name.' }],
      });
    }
    return Response.json({ name: data.name }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
