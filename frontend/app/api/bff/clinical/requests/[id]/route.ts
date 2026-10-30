import { readRequest } from '@/lib/clinical/clinicalServer';
import { withBff } from '@/lib/bff/handler';

// One clinical request, read by the clinician (W44, DEC-774): the case's glance, the reason, when a held
// request returns to the queue and, once advised, the advice. A request that is not theirs to read, or
// is nowhere, is the same 404.

const NO_STORE = { 'Cache-Control': 'no-store' };
const REQUEST_ID = /^[A-Za-z0-9-]{1,64}$/;

type Context = { params: Promise<{ id: string }> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!REQUEST_ID.test(id)) return Response.json({ code: 'not-found', message: 'We could not find that.' }, { status: 404, headers: NO_STORE });
    return Response.json({ request: await readRequest(session, id) }, { headers: NO_STORE });
  },
  { roles: ['clinical'], idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
