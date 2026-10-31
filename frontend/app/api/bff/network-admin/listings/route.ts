import { withBff } from '@/lib/bff/handler';
import { adminRead, NO_STORE } from '@/lib/networkAdmin/call';
import { ownerNetwork } from '@/lib/networkAdmin/network';
import { parseListings } from '@/lib/networkAdmin/views';

// GET: every listing of the owner's network: the organisation by name and its own reference for the
// service (a listing carries no service name yet, TEN-080 known issue).

const get = withBff(
  async (request, session) => {
    const network = await ownerNetwork(session, request);
    const listings = parseListings(await adminRead(session, `/network-admin/network/${network.id}/listings`));
    return Response.json({ network: { id: network.id, name: network.name }, listings }, { headers: NO_STORE });
  },
  { roles: ['network-admin'], allowNetworkId: true, idScoped: true },
);

export const GET = (request: Request) => get(request, undefined);
