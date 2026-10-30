import { withBff } from '@/lib/bff/handler';
import { readCriteria } from '@/lib/criteria/backend';

// The owner's view of one service's criteria (W30). Owner, clinical lead and shift lead. The back end
// does not serve the current version's values yet (R10), so this answers 503 `not-supported` until it does.

type Context = { params: Promise<{ serviceId: string }> };

const get = withBff<Context>(
  async () => readCriteria(),
  { roles: ['owner', 'clinical', 'lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
