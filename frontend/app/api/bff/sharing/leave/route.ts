import { withBff } from '@/lib/bff/handler';
import { emptyBody } from '@/lib/networkAdmin/bodies';
import { adminWrite, NO_STORE } from '@/lib/networkAdmin/call';
import { leavableNetworks, memberNetwork } from '@/lib/networkAdmin/network';
import { num, obj } from '@/lib/operator/answers';

// POST: the organisation leaves a network it is a member of (TEN-081). All its sharing ends now and what was
// already shared stays in the history, marked with the date it left. The network is the registry's answer
// for this organisation; the owner of a network cannot leave it, so a network it owns is never the one.

const post = withBff(
  async (request, session) => {
    await emptyBody(request);
    const network = await memberNetwork(session, request, leavableNetworks);
    const data = obj(await adminWrite(session, `/network-admin/network/${network.id}/leave`));
    return Response.json({ status: 'left', grantsLapsed: num(data.grants_lapsed), listingsWithdrawn: num(data.listings_withdrawn) }, { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], allowNetworkId: true, idScoped: true },
);

export const POST = (request: Request) => post(request, undefined);
