import { withBff } from '@/lib/bff/handler';
import { emptyBody } from '@/lib/networkAdmin/bodies';
import { adminWrite, NO_STORE } from '@/lib/networkAdmin/call';
import { recordIdOf } from '@/lib/networkAdmin/ids';
import { bool, obj } from '@/lib/operator/answers';

// POST: the organisation's approval of a grant (TEN-081). A grant takes two approvals, from two different people; `effective` is true when this was the second.
// The grant is named by its own handle and the back end checks that it is this organisation's, so no
// network is named here.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await recordIdOf(context);
    await emptyBody(request);
    const data = obj(await adminWrite(session, `/network-admin/grants/${id}/approve`));
    return Response.json({ effective: bool(data.effective) }, { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
