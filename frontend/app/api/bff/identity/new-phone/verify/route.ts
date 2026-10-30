import { preSession } from '@/lib/reporter/bff';
import { ensureDevice } from '@/lib/reporter/device';
import { identityCall } from '@/lib/reporter/identity';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { refuse } from '@/lib/reporter/bff';

// POST /api/bff/identity/new-phone/verify (W55). The new number's code, checked with this phone's
// device id (from its cookie). The back end's answers become three BFF codes the screen words:
// wrong (400), expired (410), throttled (429). The old phone is signed out by the back end once the
// code is right; nothing here says whether the number is known.

const NO_STORE = { 'Cache-Control': 'no-store' };

type Body = { phone?: unknown; code?: unknown };

export const POST = preSession(async (request) => {
  const body = (await request.json().catch(() => undefined)) as Body | undefined;
  if (typeof body?.phone !== 'string' || !isUkMobile(body.phone) || typeof body.code !== 'string' || body.code.length === 0) {
    return refuse(400, 'invalid');
  }
  const deviceId = await ensureDevice(request);
  const reply = await identityCall(request, {
    method: 'POST',
    path: '/identity/new-phone/verify',
    body: { phone: body.phone, code: body.code, deviceId },
  });
  if (reply.status === 200) {
    // The tenant's coordination number for the wait (DEC-825), or null when it has set none.
    const number = (reply.body as { spoaPhone?: unknown } | undefined)?.spoaPhone;
    const spoaPhone = typeof number === 'string' && number.length > 0 && number.length <= 32 ? number : null;
    return Response.json({ status: 'pending-callback', spoaPhone }, { headers: NO_STORE });
  }
  if (reply.status === 429) return Response.json({ code: 'throttled' }, { status: 429, headers: NO_STORE });
  if (reply.status === 400) {
    const expired = JSON.stringify(reply.body ?? {}).includes('Ask for a new code');
    return expired
      ? Response.json({ code: 'expired' }, { status: 410, headers: NO_STORE })
      : Response.json({ code: 'wrong' }, { status: 400, headers: NO_STORE });
  }
  if (reply.status === 409) return Response.json({ code: 'device-refused' }, { status: 409, headers: NO_STORE });
  return Response.json({ code: 'unavailable' }, { status: 503, headers: NO_STORE });
});
