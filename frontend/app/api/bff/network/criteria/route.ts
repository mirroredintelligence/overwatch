import { withBff } from '@/lib/bff/handler';
import { NETWORK_VIEW_ROLES } from '@/lib/network/availability';
import { parseCriteria } from '@/lib/network/parse';
import { networkIdOf, readNetwork, historyQuery } from '@/lib/network/server';

// The network criteria (TEN-068). The network is the `networkId` the server offered, checked against the registry on
// every call; the answer is rebuilt from the fields the page uses.

const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff(
  async (request, session) =>
    Response.json(await readNetwork(session, networkIdOf(request), 'criteria', (body) => parseCriteria(body, 'backend'), historyQuery(request)), { headers: NO_STORE }),
  { roles: NETWORK_VIEW_ROLES, allowNetworkId: true, idScoped: true },
);

export const GET = (request: Request) => get(request, undefined);
