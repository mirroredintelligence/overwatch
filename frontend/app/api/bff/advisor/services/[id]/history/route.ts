import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { parseHistory } from '@/lib/advisor/history';
import { routeId } from '@/lib/lead/bffInput';

// What a service reported over the last day, for the day chart (DEC-1343). The back end answers at its root; the answer
// is checked against the shape the chart knows before it is passed on, so a malformed answer is an error and never a
// drawn guess. Advisor, Advisor v2, Analytics User (DEC-1366), clinical advisor and shift lead. The id is a service of the session's own tenant (DEC-130).

type Context = { params: Promise<Record<string, string>> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const id = await routeId(context, 'id');
    const { data } = await fhirFetch<unknown>(`/clinical/services/${encodeURIComponent(id)}/history`, {
      root: true,
      token: session.backendToken,
      cache: 'no-store',
    });
    return Response.json(parseHistory(data), { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['advisor', 'advisor-v2', 'analytics-user', 'clinical', 'lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
