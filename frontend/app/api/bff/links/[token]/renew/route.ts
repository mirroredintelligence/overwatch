import { checkRenewCsrf } from '@/lib/links/csrf';
import { callLinkApi, hostOf, publicReply } from '@/lib/links/server';

// Asks for a fresh link to an expired link. No session: the request names no tenant and takes no body.
// It carries the renewal CSRF token the closed link's answer gave the page (KI-178), which a page of
// another origin cannot read, so a forged request is refused before the back end is asked. The back end
// answers 202 for every token and host; only a spent budget answers 429, so the page can say to wait.

const NO_STORE = { 'Cache-Control': 'no-store' };
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;

type Context = { params: Promise<{ token: string }> };

export async function POST(request: Request, context: Context): Promise<Response> {
  const { token } = await context.params;
  if (!TOKEN_SHAPE.test(token)) {
    return Response.json({ state: 'accepted' }, { status: 202, headers: NO_STORE });
  }
  if (!checkRenewCsrf(request, token)) {
    return Response.json({ state: 'forbidden' }, { status: 403, headers: NO_STORE });
  }
  try {
    const answer = await callLinkApi({
      method: 'POST',
      path: `/links/${token}/renew`,
      host: hostOf(request),
    });
    const result = publicReply(answer.status, answer.body);
    const headers: Record<string, string> = { ...NO_STORE };
    if (result.status === 429 && answer.retryAfter !== undefined && /^\d{1,6}$/.test(answer.retryAfter)) {
      headers['Retry-After'] = answer.retryAfter;
    }
    return Response.json(result.body, { status: result.status, headers });
  } catch {
    return Response.json({ state: 'unavailable' }, { status: 503, headers: NO_STORE });
  }
}
