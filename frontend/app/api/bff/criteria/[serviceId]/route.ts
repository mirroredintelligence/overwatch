import { withBff } from '@/lib/bff/handler';
import { readCriteria } from '@/lib/criteria/backend';
import { bffJson, refuse } from '@/lib/register/requests';

// The owner's view of one service's criteria (W30). Owner, clinical lead and shift lead. The back end
// decides per service: a service the caller holds no criteria for is the one not-found answer.

type Context = { params: Promise<{ serviceId: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

const get = withBff<Context>(
  async (_request, session, context) => {
    const { serviceId } = await context.params;
    if (!ID.test(serviceId)) return refuse(404, 'not-found', 'We could not find that.');
    return bffJson(200, await readCriteria(session.backendToken, serviceId));
  },
  { idScoped: true, roles: ['owner', 'clinical', 'lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
