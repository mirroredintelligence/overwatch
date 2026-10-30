import { withBff } from '@/lib/bff/handler';
import { notBuilt } from '@/lib/lead/notBuilt';

// Sends a test prompt to a service that was just set up (W18). Lead only, CSRF. The back end's synthetic
// hook is a test route for the reporter loop, not for a lead, so this answers 501 and sends nothing
// (DEC-651).

const post = withBff(async () => notBuilt(), { roles: ['lead'] });

export const POST = (request: Request, context: { params: Promise<{ id: string }> }) => post(request, context);
