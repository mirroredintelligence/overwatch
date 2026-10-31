import { withBff } from '@/lib/bff/handler';
import { adminRead, NO_STORE } from '@/lib/networkAdmin/call';
import { ownerNetwork } from '@/lib/networkAdmin/network';
import { parseGrants } from '@/lib/networkAdmin/views';

// GET: every grant of the owner's network, by the organisation's name (TEN-080). The owner approves or
// declines here; it cannot end a member's grant (only the grantor does, DEC-132 item 3).

const get = withBff(
  async (request, session) => {
    const network = await ownerNetwork(session, request);
    const grants = parseGrants(await adminRead(session, `/network-admin/network/${network.id}/grants`));
    return Response.json({ network: { id: network.id, name: network.name }, grants }, { headers: NO_STORE });
  },
  { roles: ['network-admin'], allowNetworkId: true, idScoped: true },
);

export const GET = (request: Request) => get(request, undefined);
