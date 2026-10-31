import { withBff } from '@/lib/bff/handler';
import { jsonBody } from '@/lib/lead/bffInput';
import { acceptBody } from '@/lib/networkAdmin/bodies';
import { adminWrite, NO_STORE } from '@/lib/networkAdmin/call';
import { acceptableNetworks, memberNetwork } from '@/lib/networkAdmin/network';

// POST: the organisation accepts the version of the agreement it has read (TEN-081): the first one, for an
// invitation, or a newer one. The membership is the registry's, found from the network the server chose for
// this organisation: the browser holds no handle for it and sends none. A version that is not the network's
// current one is the back end's 409. The agreement's content is never here: only its version.

const post = withBff(
  async (request, session) => {
    const body = acceptBody(await jsonBody(request));
    const network = await memberNetwork(session, request, acceptableNetworks);
    await adminWrite(session, `/network-admin/memberships/${network.membershipId}/accept`, body);
    return Response.json({ status: 'active' }, { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], allowNetworkId: true, idScoped: true },
);

export const POST = (request: Request) => post(request, undefined);
