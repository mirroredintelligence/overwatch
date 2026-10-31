import { withBff } from '@/lib/bff/handler';
import { jsonBody } from '@/lib/lead/bffInput';
import { proposeBody } from '@/lib/networkAdmin/bodies';
import { adminWrite, NO_STORE } from '@/lib/networkAdmin/call';
import { activeNetworks, memberNetwork } from '@/lib/networkAdmin/network';
import { obj, str } from '@/lib/operator/answers';

// POST: proposes sharing one kind with the network (TEN-081). The kind is all the browser says: the network is
// the registry's answer for this organisation (the one it is in, or the one the page names among those it was
// offered), the window starts now and has no end, and the grant waits for two approvals, the organisation's
// and the network owner's, from two different people. A kind that already has an open grant is a 409.

const post = withBff(
  async (request, session) => {
    const body = proposeBody(await jsonBody(request));
    const network = await memberNetwork(session, request, activeNetworks);
    const data = obj(await adminWrite(session, '/network-admin/grants', { network_id: network.id, scope: body.scope }));
    return Response.json({ id: str(data.id, 64), status: 'proposed' }, { status: 201, headers: NO_STORE });
  },
  { roles: ['tenant-admin'], allowNetworkId: true, idScoped: true },
);

export const POST = (request: Request) => post(request, undefined);
