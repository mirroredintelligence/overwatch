import { withBff } from '@/lib/bff/handler';
import { adminRead, NO_STORE } from '@/lib/networkAdmin/call';
import { chooseNetwork, listNetworks, namedNetwork, ownedNetworks } from '@/lib/networkAdmin/network';
import { parseMembers, parseProjection } from '@/lib/networkAdmin/views';

// GET: what the network administrator of the owning organisation sees on /network-admin (TEN-080): the
// networks it owns (offered, so one can be chosen), and for the one in question its members and what each
// member's sharing is (states and dates, never a row). The owner reads no member's private data (DEC-132
// item 2). The registry is asked first; the network is named in the path of the calls that follow and
// nowhere else. With several owned networks and none named, the list is answered and none is chosen.

const get = withBff(
  async (request, session) => {
    const owned = ownedNetworks(await listNetworks(session));
    const offered = owned.map((n) => ({ id: n.id, name: n.name }));
    const named = namedNetwork(request);
    if (named === null && owned.length > 1) return Response.json({ networks: offered, network: null }, { headers: NO_STORE });
    const network = chooseNetwork(owned, named);
    const members = parseMembers(await adminRead(session, `/network-admin/network/${network.id}/members`));
    const health = parseProjection(await adminRead(session, `/network-admin/network/${network.id}/projection`));
    return Response.json(
      {
        networks: offered,
        network: {
          id: network.id,
          name: network.name,
          agreementReference: network.agreementReference,
          agreementVersion: network.agreementVersion,
          members,
          health,
        },
      },
      { headers: NO_STORE },
    );
  },
  { roles: ['network-admin'], allowNetworkId: true, idScoped: true },
);

export const GET = (request: Request) => get(request, undefined);
