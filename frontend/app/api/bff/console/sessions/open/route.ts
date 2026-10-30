import { withBff } from '@/lib/bff/handler';
import { CONSOLE_ROLES, consoleCall, jsonBody, NO_STORE, shortText } from '@/lib/console/backend';

// Opens one session for reading: with the support code the person shared, or with an approved
// ticket (W48). The back end logs every open. The browser sends one of the two and nothing else
// that matters; any tenant field is ignored, because the tenant comes from the code.

type OpenResult = { sessionId: string; expiresAt: string };

const post = withBff(
  async (request, session) => {
    const body = await jsonBody(request);
    const code = body === null ? undefined : shortText(body, 'supportCode');
    const ticket = body === null ? undefined : shortText(body, 'ticket');
    if ((code === undefined) === (ticket === undefined)) {
      return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    }
    const sent = code !== undefined ? { supportCode: code } : { ticket };
    const { data } = await consoleCall<OpenResult>(session, '/support/sessions/open', {
      method: 'POST',
      body: sent,
      // The back end wants one per request (its own replay rule); a fresh one is never a repeat.
      idempotencyKey: crypto.randomUUID(),
    });
    return Response.json(
      { sessionId: data.sessionId, expiresAt: data.expiresAt },
      { headers: NO_STORE },
    );
  },
  { roles: [...CONSOLE_ROLES] },
);

export const POST = (request: Request) => post(request, undefined);
