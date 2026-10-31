import { withBff } from '@/lib/bff/handler';
import { FhirError } from '@/lib/fhir/client';
import { jsonBody } from '@/lib/lead/bffInput';
import { inviteBody } from '@/lib/networkAdmin/bodies';
import { adminWrite, NO_STORE } from '@/lib/networkAdmin/call';
import { notFound } from '@/lib/networkAdmin/ids';
import { ownerNetwork } from '@/lib/networkAdmin/network';
import { obj, str } from '@/lib/operator/answers';

// POST: invites an organisation to the network by its organisation code (TEN-080, DEC-136 item 3). The
// code is the only way to name one, so no list of other organisations is ever shown; an unknown code, an
// organisation that cannot be invited and one already in or invited to the network all answer the same 404
// with the same words. The back end's field for the code is the organisation's own id, set here and never
// read from the request as such.

const post = withBff(
  async (request, session) => {
    const body = inviteBody(await jsonBody(request));
    const network = await ownerNetwork(session, request);
    try {
      const data = obj(await adminWrite(session, `/network-admin/network/${network.id}/members`, body));
      return Response.json({ id: str(data.membership_id, 64), status: 'invited' }, { status: 201, headers: NO_STORE });
    } catch (error) {
      if (error instanceof FhirError && (error.status === 404 || error.status === 409)) throw notFound();
      throw error;
    }
  },
  { roles: ['network-admin'], allowNetworkId: true, idScoped: true },
);

export const POST = (request: Request) => post(request, undefined);
