import { withBff } from '@/lib/bff/handler';
import { parseNetworkOptions } from '@/lib/network/options';
import { caseQuery, networkIdOf, readNetwork } from '@/lib/network/server';

// The advisor's network options (WB11, docs/design/network-ui.md section 9): the services of the OTHER
// organisations in a network that may take the advisor's case, read only. The network is the `networkId` the
// server offered, checked against the registry on every call. The case is the advisor's own case reference:
// the query holds nothing else of it (no postcode, need or age), and the back end reads the case in the
// advisor's own tenant and compares it, in memory, with what the network shares. The roles are the ones that
// work a case; the answer is rebuilt from the fields the page uses.

const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff(
  async (request, session) => {
    const networkId = networkIdOf(request);
    const query = caseQuery(request);
    return Response.json(await readNetwork(session, networkId, 'options', (body) => parseNetworkOptions(body, 'backend'), query), { headers: NO_STORE });
  },
  { roles: ['advisor', 'clinical'], allowNetworkId: true, idScoped: true },
);

export const GET = (request: Request) => get(request, undefined);
