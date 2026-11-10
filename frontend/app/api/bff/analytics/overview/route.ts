import { withBff } from '@/lib/bff/handler';
import { parseAnalyticsOverview } from '@/lib/analytics/parse';
import { fhirFetch } from '@/lib/fhir/client';

// The Analytics User's overview (DEC-1368): counts, services with their districts and figures, and the two lists of
// what needs attention. Analytics User only. The back end's read is at its root, not under /fhir. The answer is
// checked against the shape the page knows before it is passed on, and only the known fields are kept. It takes no
// tenant from the request (DEC-130, DEC-132); the token is the tenant's.

const get = withBff(
  async (_request, session) => {
    const { data } = await fhirFetch<unknown>('/analytics/overview', { root: true, token: session.backendToken, cache: 'no-store' });
    return Response.json(parseAnalyticsOverview(data), { headers: { 'Cache-Control': 'no-store' } });
  },
  { roles: ['analytics-user'] },
);

export const GET = (request: Request) => get(request, undefined);
