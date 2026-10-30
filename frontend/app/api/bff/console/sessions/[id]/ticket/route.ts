import { withBff } from '@/lib/bff/handler';
import { CONSOLE_ROLES, consoleCall, jsonBody, NO_STORE, sessionIdOf, shortText } from '@/lib/console/backend';

// Ask for a ticket to open a session that no code opens (W48). The lead approves it on the back end.

type Context = { params: Promise<{ id: string }> };

const post = withBff<Context>(
  async (request, session, context) => {
    const sessionId = sessionIdOf((await context.params).id);
    const body = await jsonBody(request);
    const ticket = body === null ? undefined : shortText(body, 'ticket');
    if (sessionId === null || ticket === undefined) {
      return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    }
    const { data } = await consoleCall<{ state: string }>(
      session,
      `/support/sessions/${encodeURIComponent(sessionId)}/ticket`,
      { method: 'POST', body: { ticket }, idempotencyKey: crypto.randomUUID() },
    );
    return Response.json({ state: data.state }, { headers: NO_STORE });
  },
  { roles: [...CONSOLE_ROLES] },
);

export const POST = (request: Request, context: Context) => post(request, context);
