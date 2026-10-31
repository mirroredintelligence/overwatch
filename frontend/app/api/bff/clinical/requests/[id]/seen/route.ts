import { readSeen } from '@/lib/clinical/clinicalServer';
import { withBff } from '@/lib/bff/handler';

// What the advisor saw when they asked (W9G), for the clinician who holds the request: one line per
// service, capacity only. A request that is not theirs, or is nowhere, is the same 404. Never stored.

const NO_STORE = { 'Cache-Control': 'no-store' };
const REQUEST_ID = /^[A-Za-z0-9-]{1,64}$/;

type Context = { params: Promise<{ id: string }> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!REQUEST_ID.test(id)) return Response.json({ code: 'not-found', message: 'We could not find that.' }, { status: 404, headers: NO_STORE });
    return Response.json({ seen: await readSeen(session, id) }, { headers: NO_STORE });
  },
  { roles: ['clinical'], idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
