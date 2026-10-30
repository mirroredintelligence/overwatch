import { withBff } from '@/lib/bff/handler';
import { submitChange } from '@/lib/criteria/backend';
import { changeBody } from '@/lib/criteria/request';
import { idempotencyKeyOf, idOf } from '@/lib/registration/request';

// "Send for approval" (W30): the owner's change, with its reason and review period. It is written into
// pending-approval; advisors keep seeing the current version until a clinical lead approves it. Owner only.

type Context = { params: Promise<{ serviceId: string }> };
const NO_STORE = { 'Cache-Control': 'no-store' };

const post = withBff<Context>(
  async (request, session, context) => {
    const serviceId = idOf((await context.params).serviceId);
    const input = changeBody(await request.json().catch(() => undefined));
    const key = idempotencyKeyOf(request);
    const { version, status } = await submitChange(session.backendToken, serviceId, input, key);
    return Response.json({ version, status }, { status: 201, headers: NO_STORE });
  },
  { roles: ['owner'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
