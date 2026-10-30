import { withBff } from '@/lib/bff/handler';
import { notServed } from '@/lib/registration/backend';
import { idOf } from '@/lib/registration/request';

// One registration's review overview (W28). Lead only. The back end does not serve this read yet
// (R10), so it answers 503 `not-supported` until it does.

type Context = { params: Promise<{ id: string }> };

const get = withBff<Context>(
  async (_request, _session, context) => {
    idOf((await context.params).id);
    notServed();
  },
  { roles: ['lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
