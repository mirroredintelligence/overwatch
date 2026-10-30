import { preSession } from '@/lib/reporter/bff';
import { ensureDevice } from '@/lib/reporter/device';
import { identityCall } from '@/lib/reporter/identity';

// POST /api/bff/identity/pin (W34): set the PIN of a phone verified in the last ten minutes. The
// device id is the phone's own cookie; the body carries the PIN and nothing else the browser could
// choose. The PIN is passed on and never kept.

const PIN = /^\d{6}$/;
const NO_STORE = { 'Cache-Control': 'no-store' };

export const POST = preSession(async (request) => {
  const body = (await request.json().catch(() => undefined)) as { pin?: unknown } | undefined;
  if (typeof body?.pin !== 'string' || !PIN.test(body.pin)) {
    return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
  }
  const deviceId = await ensureDevice(request);
  const reply = await identityCall(request, { method: 'POST', path: '/identity/pin', body: { deviceId, pin: body.pin } });
  if (reply.status === 200) return Response.json({ pinSet: true }, { headers: NO_STORE });
  if (reply.status === 403) return Response.json({ code: 'forbidden' }, { status: 403, headers: NO_STORE });
  return Response.json({ code: 'unavailable' }, { status: 503, headers: NO_STORE });
});
