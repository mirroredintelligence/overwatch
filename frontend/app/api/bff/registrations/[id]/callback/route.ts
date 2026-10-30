import { withBff } from '@/lib/bff/handler';
import { recordCallBack } from '@/lib/registration/backend';
import { callBackBody, idempotencyKeyOf, idOf } from '@/lib/registration/request';

// The call-back (W29, check 1 of 4). Lead only. The number called is the one the page showed from the
// register; the browser may not send any other, and the back end records what was called.

type Context = { params: Promise<{ id: string }> };
const NO_STORE = { 'Cache-Control': 'no-store' };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = idOf((await context.params).id);
    const input = callBackBody(await request.json().catch(() => undefined));
    const key = idempotencyKeyOf(request);
    return Response.json(await recordCallBack(session.backendToken, id, input, key), { headers: NO_STORE });
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
