import { withBff } from '@/lib/bff/handler';
import { adminRead, NO_STORE } from '@/lib/networkAdmin/call';
import { ownerNetwork } from '@/lib/networkAdmin/network';
import { parseMembers, parseProjection } from '@/lib/networkAdmin/views';

// GET: what the network administrator of the owning organisation sees on /network-admin (TEN-080): the
// network it runs, its members, and what each member's sharing is (states and dates, never a row). The owner
// reads no member's private data (DEC-132 item 2). The registry is asked first; the network is named in the
// path of the calls that follow and nowhere else. With several owned networks the page chooses one
// (`/networks` lists them) and names it as `networkId`.

const get = withBff(
  async (request, session) => {
    const network = await ownerNetwork(session, request);
    const members = parseMembers(await adminRead(session, `/network-admin/network/${network.id}/members`));
    const health = parseProjection(await adminRead(session, `/network-admin/network/${network.id}/projection`));
    return Response.json(
      {
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
