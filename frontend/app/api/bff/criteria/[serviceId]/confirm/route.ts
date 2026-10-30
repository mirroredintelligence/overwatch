import { withBff } from '@/lib/bff/handler';
import { confirmReview } from '@/lib/criteria/backend';
import { confirmBody } from '@/lib/criteria/request';
import { idempotencyKeyOf, idOf } from '@/lib/registration/request';

// "Still right" (W30): the owner confirms the current criteria and the review period. The back end
// answers the new review date. Owner and shift lead only (U30).

type Context = { params: Promise<{ serviceId: string }> };
const NO_STORE = { 'Cache-Control': 'no-store' };

const post = withBff<Context>(
  async (request, session, context) => {
    const serviceId = idOf((await context.params).serviceId);
    const months = confirmBody(await request.json().catch(() => undefined));
    const key = idempotencyKeyOf(request);
    return Response.json(await confirmReview(session.backendToken, serviceId, months, key), { headers: NO_STORE });
  },
  { roles: ['owner', 'lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
