import { withBff } from '@/lib/bff/handler';
import { CONSOLE_ROLES, consoleCall, NO_STORE, sessionIdOf } from '@/lib/console/backend';

// Close session (W48): ends the person's access to one session. The back end logs it.

type Context = { params: Promise<{ id: string }> };

const del = withBff<Context>(
  async (_request, session, context) => {
    const sessionId = sessionIdOf((await context.params).id);
    if (sessionId === null) return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    await consoleCall(session, `/support/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
      idempotencyKey: crypto.randomUUID(),
    });
    return new Response(null, { status: 204, headers: NO_STORE });
  },
  { roles: [...CONSOLE_ROLES] },
);

export const DELETE = (request: Request, context: Context) => del(request, context);
