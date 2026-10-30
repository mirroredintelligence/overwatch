import { withBff } from '@/lib/bff/handler';
import { readPending } from '@/lib/criteria/backend';
import { bffJson, refuse } from '@/lib/register/requests';

// The change waiting for the second approval, as the approver reads it (W31). 404 when none is waiting.

type Context = { params: Promise<{ serviceId: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

const get = withBff<Context>(
  async (_request, session, context) => {
    const { serviceId } = await context.params;
    if (!ID.test(serviceId)) return refuse(404, 'not-found', 'We could not find that.');
    return bffJson(200, await readPending(session.backendToken, serviceId));
  },
  { idScoped: true, roles: ['owner', 'clinical', 'lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
