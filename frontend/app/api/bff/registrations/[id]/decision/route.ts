import { withBff } from '@/lib/bff/handler';
import { decideRegistration } from '@/lib/registration/backend';
import { readDecision } from '@/lib/register/backend';
import { decisionFromBackend } from '@/lib/registration/mapping';
import { decisionBody, idempotencyKeyOf, idOf } from '@/lib/registration/request';
import { bffJson, refuse } from '@/lib/register/requests';

// The decision on one registration (W29, check 4 of 4). Lead only. The read of what is missing comes
// from the back end's decision read, mapped for the page. The approval gate itself is the back end's:
// approve before every check is done is refused there, never here.

type Context = { params: Promise<{ id: string }> };
const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff<Context>(
  async (_request, session, context) => {
    const id = idOf((await context.params).id);
    const decision = decisionFromBackend(await readDecision(session.backendToken, id));
    if (decision === null) return refuse(503, 'unavailable', 'We could not load the decision. Try again later.');
    return bffJson(200, decision);
  },
  { idScoped: true, roles: ['lead'] },
);

const post = withBff<Context>(
  async (request, session, context) => {
    const id = idOf((await context.params).id);
    const { action, note } = decisionBody(await request.json().catch(() => undefined));
    const key = idempotencyKeyOf(request);
    return Response.json(await decideRegistration(session.backendToken, id, action, note, key), { headers: NO_STORE });
  },
  { idScoped: true, roles: ['lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
export const POST = (request: Request, context: Context) => post(request, context);
