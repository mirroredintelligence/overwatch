import { callLinkApi, hostOf } from '@/lib/links/server';
import { issueCheckinCsrf, reply, TOKEN_SHAPE, unavailable } from '@/lib/checkin/server';

// Reads the code a service printed: which service it is for, and the CSRF token for the writes. The browser's one read
// of it, so the CSRF cookie is set by a response the browser asked for. Nothing changes on the back end.

type Context = { params: Promise<{ token: string }> };

export async function GET(request: Request, context: Context): Promise<Response> {
  const { token } = await context.params;
  if (!TOKEN_SHAPE.test(token)) return reply(410, { state: 'gone' });
  try {
    const result = await callLinkApi({ method: 'GET', path: `/checkin/${encodeURIComponent(token)}`, host: hostOf(request) });
    if (result.status === 200) {
      const body = result.body as { csrfToken?: unknown };
      if (typeof body?.csrfToken === 'string') await issueCheckinCsrf(token, body.csrfToken);
    }
    return reply(result.status, result.body);
  } catch {
    return unavailable();
  }
}
