import { withBff } from '@/lib/bff/handler';
import { recordScopeDecision } from '@/lib/registration/backend';
import { idempotencyKeyOf, idOf, scopeDecisionBody } from '@/lib/registration/request';

// The scope decision (W29, check 2 of 4). Lead only. The four answers and the flag; the reason only
// when the decision is not the pilot.

type Context = { params: Promise<{ id: string }> };
const NO_STORE = { 'Cache-Control': 'no-store' };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = idOf((await context.params).id);
    const input = scopeDecisionBody(await request.json().catch(() => undefined));
    const key = idempotencyKeyOf(request);
    return Response.json(await recordScopeDecision(session.backendToken, id, input, key), { headers: NO_STORE });
  },
  { roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
