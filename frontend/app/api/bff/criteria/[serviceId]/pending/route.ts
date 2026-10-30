import { withBff } from '@/lib/bff/handler';
import { readPending } from '@/lib/criteria/backend';

// The change waiting for the second approval, as the approver reads it (W31). The back end does not
// serve it yet (R10), so this answers 503 `not-supported` until it does.

type Context = { params: Promise<{ serviceId: string }> };

const get = withBff<Context>(async () => readPending(), { roles: ['owner', 'clinical', 'lead'] });

export const GET = (request: Request, context: Context) => get(request, context);
