import { parseInvitationAnswer } from '@/lib/reporter/answers';
import { json, plain } from '@/lib/reporter/backend';
import { identityOrUnavailable, throttled } from '@/lib/reporter/identity';

// GET /api/bff/invitations/[token] (W33, W7C DEC-810, W8E). The invitation a reporter's link names, read
// from the back end by its token in the host's tenant: the service, the post, the masked number and the
// expiry. An unknown, malformed, expired, used, another tenant's or another purpose's token is one 410
// `{state: "expired"}`, so an unknown link tells nobody whether it ever existed. "valid" is said only
// when the back end said it, with the fields checked; a failed check is "unavailable", never "expired".
// No session, no bearer, no cookie: the tenant is the host the phone came to.

const NO_STORE = { 'Cache-Control': 'no-store' };
const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;
const EXPIRED = () => Response.json({ state: 'expired' }, { status: 410, headers: NO_STORE });

type Context = { params: Promise<{ token: string }> };

export async function GET(request: Request, context: Context): Promise<Response> {
  const { token } = await context.params;
  if (!TOKEN_SHAPE.test(token)) return EXPIRED();
  const reply = await identityOrUnavailable(request, { method: 'GET', path: `/invitations/${token}` });
  if (reply instanceof Response) return reply;
  if (reply.status === 410) return EXPIRED();
  if (reply.status === 429) return throttled(reply);
  const parsed = reply.status === 200 ? parseInvitationAnswer(reply.body) : null;
  return parsed === null ? plain(503, 'unavailable') : json(parsed);
}
