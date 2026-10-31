import { withBff } from '@/lib/bff/handler';
import { jsonBody } from '@/lib/lead/bffInput';
import { agreementBody } from '@/lib/networkAdmin/bodies';
import { adminWrite, NO_STORE } from '@/lib/networkAdmin/call';
import { ownerNetwork } from '@/lib/networkAdmin/network';
import { num, obj } from '@/lib/operator/answers';

// POST: records a new version of the data sharing agreement (TEN-080): its reference in the owner's own
// document system and its version, never its content. Members then show as behind until they accept.

const post = withBff(
  async (request, session) => {
    const body = agreementBody(await jsonBody(request));
    const network = await ownerNetwork(session, request);
    const data = obj(await adminWrite(session, `/network-admin/network/${network.id}/agreement`, body));
    return Response.json({ agreementVersion: num(data.agreement_version) }, { headers: NO_STORE });
  },
  { roles: ['network-admin'], allowNetworkId: true, idScoped: true },
);

export const POST = (request: Request) => post(request, undefined);
