import { withBff } from '@/lib/bff/handler';
import { CONSOLE_ROLES, consoleCall, NO_STORE, TRACE_ID_PATTERN } from '@/lib/console/backend';

// One trace's spans, for the waterfall (W48). The trace id must be 32 lower-case hex characters.

type Context = { params: Promise<{ traceId: string }> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const { traceId } = await context.params;
    if (!TRACE_ID_PATTERN.test(traceId)) {
      return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    }
    const { data } = await consoleCall(session, `/support/traces/${traceId}`);
    return Response.json(data, { headers: NO_STORE });
  },
  { roles: [...CONSOLE_ROLES] },
);

export const GET = (request: Request, context: Context) => get(request, context);
