import { withBff } from '@/lib/bff/handler';
import { decidePending } from '@/lib/criteria/backend';
import { pendingDecisionBody } from '@/lib/criteria/request';
import { idempotencyKeyOf, idOf } from '@/lib/registration/request';

// The second approval's decision (W31): approve the waiting version, or send it back with a note.
// The back end decides who may: the author is refused, and so is anyone but a clinical lead (a
// non-revealing 404). Nothing here checks the approver, so nothing here can be wrong about it.

type Context = { params: Promise<{ serviceId: string }> };
const NO_STORE = { 'Cache-Control': 'no-store' };

const post = withBff<Context>(
  async (request, session, context) => {
    const serviceId = idOf((await context.params).serviceId);
    const { decision, note } = pendingDecisionBody(await request.json().catch(() => undefined));
    const key = idempotencyKeyOf(request);
    return Response.json(await decidePending(session.backendToken, serviceId, decision, note, key), { headers: NO_STORE });
  },
  { idScoped: true, roles: ['owner', 'clinical', 'lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
