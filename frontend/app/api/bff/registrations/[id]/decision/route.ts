import { withBff } from '@/lib/bff/handler';
import { decideRegistration, notServed } from '@/lib/registration/backend';
import { decisionBody, idempotencyKeyOf, idOf } from '@/lib/registration/request';

// The decision on one registration (W29, check 4 of 4). Lead only. The read of what is missing is not
// served by the back end yet (R10), so GET answers 503 until it is. The approval gate itself is the
// back end's: approve before every check is done is refused there, never here.

type Context = { params: Promise<{ id: string }> };
const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff<Context>(
  async (_request, _session, context) => {
    idOf((await context.params).id);
    notServed();
  },
  { roles: ['lead'] },
);

const post = withBff<Context>(
  async (request, session, context) => {
    const id = idOf((await context.params).id);
    const { action, note } = decisionBody(await request.json().catch(() => undefined));
    const key = idempotencyKeyOf(request);
    return Response.json(await decideRegistration(session.backendToken, id, action, note, key), { headers: NO_STORE });
  },
  { roles: ['lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
export const POST = (request: Request, context: Context) => post(request, context);
