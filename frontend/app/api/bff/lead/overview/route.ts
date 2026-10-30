import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { parseOverview } from '@/lib/lead/parse';

// The shift lead's overview (W17): chasing with the ladder, figures getting old, who is covering, the system
// counts and the reports today. Lead only. The back end's read is at its root, not under /fhir (DEC-802). The
// answer is checked against the shape the page knows before it is passed on, so a malformed answer is an error
// and never a partly filled page (H-330). It takes no tenant from the request (DEC-130, DEC-132).

const get = withBff(
  async (_request, session) => {
    const { data } = await fhirFetch<unknown>('/lead/overview', { root: true, token: session.backendToken, cache: 'no-store' });
    return Response.json(parseOverview(data), { headers: { 'Cache-Control': 'no-store' } });
  },
  { roles: ['lead'] },
);

export const GET = (request: Request) => get(request, undefined);
