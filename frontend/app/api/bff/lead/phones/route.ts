import { withBff } from '@/lib/bff/handler';
import { notBuilt } from '@/lib/lead/notBuilt';

// The phones and the services they report for (W43). Lead only. The back end lists no phones yet, so this
// answers 501 and never an empty list (H-330). A phone is never shown in full, by this route or any other.

const get = withBff(async () => notBuilt(), { roles: ['lead'] });

export const GET = (request: Request) => get(request, undefined);
