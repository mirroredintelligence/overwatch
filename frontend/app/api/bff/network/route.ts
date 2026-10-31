import { withBff } from '@/lib/bff/handler';
import { NETWORK_VIEW_ROLES } from '@/lib/network/availability';
import { readNetworkList } from '@/lib/network/server';

// The networks this session may see, and the viewer's own organisation's name (TEN-068). The back end
// answers from the registry for the session's tenant (the token), so nothing here takes a tenant,
// a scope or a network from the request, and this route refuses the `networkId` key: it offers networks,
// it does not take one. A tenant in no network gets an empty list, never an error that says why.

const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff(async (_request, session) => Response.json(await readNetworkList(session), { headers: NO_STORE }), {
  roles: NETWORK_VIEW_ROLES,
});

export const GET = (request: Request) => get(request, undefined);
