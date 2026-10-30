import { withBff } from '@/lib/bff/handler';
import { notServed } from '@/lib/registration/backend';
import { idOf } from '@/lib/registration/request';

// Send the test notification again (W29, go live). The back end has no route for it yet (R10), so
// this answers 503 `not-supported` until it does. Nothing is sent from here.

type Context = { params: Promise<{ id: string }> };

const post = withBff<Context>(
  async (_request, _session, context) => {
    idOf((await context.params).id);
    notServed();
  },
  { roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
