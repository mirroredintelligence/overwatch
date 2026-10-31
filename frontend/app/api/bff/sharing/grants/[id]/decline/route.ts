import { withBff } from '@/lib/bff/handler';
import { emptyBody } from '@/lib/networkAdmin/bodies';
import { adminWrite, NO_STORE } from '@/lib/networkAdmin/call';
import { recordIdOf } from '@/lib/networkAdmin/ids';

// POST: the organisation declines a grant before both approvals are given (TEN-081).
// The grant is named by its own handle and the back end checks that it is this organisation's, so no
// network is named here.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await recordIdOf(context);
    await emptyBody(request);
    await adminWrite(session, `/network-admin/grants/${id}/decline`);
    return Response.json({ status: 'declined' }, { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
