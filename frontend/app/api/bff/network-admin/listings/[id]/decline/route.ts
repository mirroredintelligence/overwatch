import { withBff } from '@/lib/bff/handler';
import { jsonBody } from '@/lib/lead/bffInput';
import { reasonBody } from '@/lib/networkAdmin/bodies';
import { adminWrite, NO_STORE } from '@/lib/networkAdmin/call';
import { recordIdOf } from '@/lib/networkAdmin/ids';
import { ownerNetwork } from '@/lib/networkAdmin/network';

// POST: the network owner's decision on a listing, `decline` (TEN-080). A reason is one of the fixed codes,
// never free text.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await recordIdOf(context);
    const body = reasonBody(await jsonBody(request));
    const network = await ownerNetwork(session, request);
    await adminWrite(session, `/network-admin/network/${network.id}/listings/${id}/decline`, body);
    return Response.json({ status: 'done' }, { headers: NO_STORE });
  },
  { roles: ['network-admin'], allowNetworkId: true, idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
