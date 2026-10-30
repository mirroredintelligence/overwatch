import { withBff } from '@/lib/bff/handler';
import { addScopeEntry, readScopeList } from '@/lib/registration/backend';
import { idempotencyKeyOf, scopeEntryBody } from '@/lib/registration/request';

// The scope list (W28): read it, and add an entry to it. Lead only. The back end answers the
// browser's own tenant only (the token), so no organisation is taken from the request (DEC-130).

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES = ['lead'] as const;

const get = withBff(
  async (_request, session) => Response.json(await readScopeList(session.backendToken), { headers: NO_STORE }),
  { roles: [...ROLES] },
);

const post = withBff(
  async (request, session) => {
    const input = scopeEntryBody(await request.json().catch(() => undefined));
    const key = idempotencyKeyOf(request);
    const { serviceId } = await addScopeEntry(session.backendToken, input, key);
    return Response.json({ serviceId }, { status: 201, headers: NO_STORE });
  },
  { roles: [...ROLES] },
);

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
export const POST = (request: Request) => post(request, undefined);
