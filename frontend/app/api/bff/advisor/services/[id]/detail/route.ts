import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { parseServiceDetail } from '@/lib/advisor/serviceDetail';
import { routeId } from '@/lib/lead/bffInput';

// What the one service detail page shows (DEC-1367): the service's figures and reporting, its own contact number, opening
// hours, criteria and the districts it covers. The back end answers at its root; the answer is checked against the
// shape the page knows before it is passed on, so a malformed answer is an error and never a drawn guess. Advisor,
// Advisor v2 and Analytics User. The id is a service of the session's own tenant (DEC-130).

type Context = { params: Promise<Record<string, string>> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const id = await routeId(context, 'id');
    const { data } = await fhirFetch<unknown>(`/clinical/services/${encodeURIComponent(id)}/detail`, {
      root: true,
      token: session.backendToken,
      cache: 'no-store',
    });
    return Response.json(parseServiceDetail(data), { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['advisor', 'advisor-v2', 'analytics-user'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
