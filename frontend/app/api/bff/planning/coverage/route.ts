import { withBff } from '@/lib/bff/handler';
import { NO_STORE } from '@/lib/console/backend';
import { fhirFetch } from '@/lib/fhir/client';
import { PLANNING_ROLES } from '@/lib/planning/backend';
import { isWindow, parseCoverage } from '@/lib/areas/types';

// Coverage by time of day (RadarWeb 4): which postcode districts a visiting service covers in the window, and
// the referrals that came from districts nobody covers. For the lead and the executive, as the planning view.
// The back end's route is a root path, not under /fhir, like /planning. IT DOES NOT EXIST YET (lib/areas/
// types.ts holds the contract); until it does the back end answers 404 and this route answers the same 404.
// The browser names only the window, from a list. The answer is read by shape and sent on only as read: a
// field the screen does not show does not pass through.

const get = withBff(
  async (request, session) => {
    const asked = new URL(request.url).searchParams.getAll('window');
    const window = asked[0] ?? 'all';
    if (asked.length > 1 || !isWindow(window)) return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    const { data } = await fhirFetch<unknown>(`/planning/coverage?window=${window}`, {
      root: true,
      token: session.backendToken,
    });
    const view = parseCoverage(data);
    if (view === null) return Response.json({ code: 'exception' }, { status: 502, headers: NO_STORE });
    return Response.json(view, { headers: NO_STORE });
  },
  { roles: [...PLANNING_ROLES] },
);

export const GET = (request: Request) => get(request, undefined);
