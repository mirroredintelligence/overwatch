import { withBff } from '@/lib/bff/handler';
import { notBuilt } from '@/lib/lead/notBuilt';

// The shift lead's overview (W17): chasing, figures getting old, covering, the system counts. Lead only.
// The back end has no read that gives the chasing ladder, the figures getting old or the covering numbers
// yet, so this answers 501 and never an empty overview (H-330, DEC-651). It takes no tenant or organisation
// from the request (DEC-130, DEC-132).

const get = withBff(async () => notBuilt(), { roles: ['lead'] });

export const GET = (request: Request) => get(request, undefined);

