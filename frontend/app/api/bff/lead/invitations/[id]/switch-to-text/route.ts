import { withBff } from '@/lib/bff/handler';
import { idempotencyKeyOf, routeId } from '@/lib/lead/bffInput';
import { notBuilt } from '@/lib/lead/notBuilt';

// Switches an invited reporter to text (W43). Lead only, CSRF. The back end has no switch yet: 501 (DEC-651).

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, _session, context) => {
    await routeId(context, 'id');
    idempotencyKeyOf(request);
    return notBuilt();
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
