import { withBff } from '@/lib/bff/handler';
import { setServiceLive } from '@/lib/registration/backend';
import { idempotencyKeyOf, idOf } from '@/lib/registration/request';

// Set the service live (W29, go live). Lead only. The back end refuses it until the test is answered.

type Context = { params: Promise<{ id: string }> };
const NO_STORE = { 'Cache-Control': 'no-store' };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = idOf((await context.params).id);
    const key = idempotencyKeyOf(request);
    return Response.json(await setServiceLive(session.backendToken, id, key), { headers: NO_STORE });
  },
  { roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
