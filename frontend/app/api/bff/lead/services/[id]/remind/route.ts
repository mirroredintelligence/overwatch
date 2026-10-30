import { withBff } from '@/lib/bff/handler';
import { notBuilt } from '@/lib/lead/notBuilt';

// Asks a service for a fresh figure again (W17). Lead only, CSRF checked on every POST (withBff). The back
// end has no reminder route yet, so this answers 501 and sends nothing (DEC-651).

const post = withBff(async () => notBuilt(), { idScoped: true, roles: ['lead'] });

export const POST = (request: Request, context: { params: Promise<{ id: string }> }) => post(request, context);
