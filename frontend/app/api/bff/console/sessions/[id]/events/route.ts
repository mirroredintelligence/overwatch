import { withBff } from '@/lib/bff/handler';
import { CONSOLE_ROLES, consoleCall, NO_STORE, sessionIdOf } from '@/lib/console/backend';

// One session's timeline (W48). The filter is one of five names; anything else is refused.

type Context = { params: Promise<{ id: string }> };

const FILTERS = ['all', 'errors', 'friction', 'api', 'navigation'];

const get = withBff<Context>(
  async (request, session, context) => {
    const sessionId = sessionIdOf((await context.params).id);
    const filter = new URL(request.url).searchParams.get('filter') ?? 'all';
    if (sessionId === null || !FILTERS.includes(filter)) {
      return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    }
    const { data } = await consoleCall(
      session,
      `/support/sessions/${encodeURIComponent(sessionId)}/events?filter=${filter}`,
    );
    return Response.json(data, { headers: NO_STORE });
  },
  { roles: [...CONSOLE_ROLES] },
);

export const GET = (request: Request, context: Context) => get(request, context);
