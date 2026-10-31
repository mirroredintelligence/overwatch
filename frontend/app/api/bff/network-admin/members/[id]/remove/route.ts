import { withBff } from '@/lib/bff/handler';
import { emptyBody } from '@/lib/networkAdmin/bodies';
import { adminWrite, NO_STORE } from '@/lib/networkAdmin/call';
import { recordIdOf } from '@/lib/networkAdmin/ids';
import { ownerNetwork } from '@/lib/networkAdmin/network';
import { num, obj } from '@/lib/operator/answers';

// POST: ends a member's membership (TEN-080). Its sharing stops now and what it already shared stays in the
// history, marked with the date. The member is named by the membership's own handle; one that is not this
// network's is the one 404. The answer says how much ended (grants, listings), never who.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const membership = await recordIdOf(context);
    await emptyBody(request);
    const network = await ownerNetwork(session, request);
    const data = obj(await adminWrite(session, `/network-admin/network/${network.id}/members/${membership}/remove`));
    return Response.json({ status: 'removed', grantsLapsed: num(data.grants_lapsed), listingsWithdrawn: num(data.listings_withdrawn) }, { headers: NO_STORE });
  },
  { roles: ['network-admin'], allowNetworkId: true, idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
