import { withBff } from '@/lib/bff/handler';
import { NETWORK_WEEK_ROLES } from '@/lib/network/availability';
import { parseWeek } from '@/lib/network/parse';
import { networkIdOf, readNetwork } from '@/lib/network/server';
import { weekStartQuery } from '@/lib/network/week';

// The network's week summary (TEN-082, `GET /network/{id}/week`): capacity-derived measures only, small
// groups hidden by the back end, no breakdown by member. The executive and the shift lead only. The week
// is a Monday the caller names; one that is not, or none, is refused before the back end is asked.

const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff(
  async (request, session) => {
    const networkId = networkIdOf(request);
    const query = weekStartQuery(request);
    return Response.json(await readNetwork(session, networkId, 'week', (body) => parseWeek(body, 'backend'), query), { headers: NO_STORE });
  },
  { roles: NETWORK_WEEK_ROLES, allowNetworkId: true, idScoped: true },
);

export const GET = (request: Request) => get(request, undefined);
