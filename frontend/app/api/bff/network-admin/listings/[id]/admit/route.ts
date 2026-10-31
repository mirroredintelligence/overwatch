import { withBff } from '@/lib/bff/handler';
import { emptyBody } from '@/lib/networkAdmin/bodies';
import { adminWrite, NO_STORE } from '@/lib/networkAdmin/call';
import { recordIdOf } from '@/lib/networkAdmin/ids';
import { ownerNetwork } from '@/lib/networkAdmin/network';

// POST: the network owner's decision on a listing, `admit` (TEN-080). It takes no reason.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await recordIdOf(context);
    await emptyBody(request);
    const network = await ownerNetwork(session, request);
    await adminWrite(session, `/network-admin/network/${network.id}/listings/${id}/admit`);
    return Response.json({ status: 'done' }, { headers: NO_STORE });
  },
  { roles: ['network-admin'], allowNetworkId: true, idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
