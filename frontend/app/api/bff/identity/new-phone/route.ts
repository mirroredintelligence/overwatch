import { preSession, refuse } from '@/lib/reporter/bff';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { identityCall } from '@/lib/reporter/identity';

// POST /api/bff/identity/new-phone (W55). The lost phone's code goes to the new number. The back end
// answers 202 whatever the number is, and so does this route: nothing reveals whether it is known.

const NO_STORE = { 'Cache-Control': 'no-store' };

export const POST = preSession(async (request) => {
  const body = (await request.json().catch(() => undefined)) as { phone?: unknown } | undefined;
  if (typeof body?.phone !== 'string' || !isUkMobile(body.phone)) return refuse(400, 'invalid');
  const reply = await identityCall(request, { method: 'POST', path: '/identity/new-phone', body: { phone: body.phone } });
  if (reply.status !== 202) return Response.json({ code: 'unavailable' }, { status: 503, headers: NO_STORE });
  return Response.json({ accepted: true, resendAfterSeconds: 60 }, { status: 202, headers: NO_STORE });
});
