import { answer, refuse } from '@/lib/advisor/http';
import { parseOverview } from '@/lib/advisor/v2/overview';
import { V2_ROLES } from '@/lib/advisor/v2/roles';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';

// The capacity overview of Advisor v2 (DEC-1366): the five counts, the Needs attention lists and one row per service.
// It takes no input: the tenant is the session's, never the caller's.

const get = withBff(
  async (_request, session) => {
    const { data } = await fhirFetch<unknown>('/advisor-v2/capacity', {
      root: true,
      token: session.backendToken,
      cache: 'no-store',
    });
    if (parseOverview(data) === null) return refuse(502, 'exception');
    return answer(data);
  },
  { roles: [...V2_ROLES] },
);

export const GET = (request: Request) => get(request, undefined);
