import { withBff } from '@/lib/bff/handler';
import { notBuilt, refuse } from '@/lib/reporter/bff';
import { ensureDevice } from '@/lib/reporter/device';
import { identityCall } from '@/lib/reporter/identity';

// POST /api/bff/push/subscriptions (W34). Saves the browser's subscription with its consent
// wording, through the back end's push-subscription route (R11). That route needs the signed-in
// reporter's bearer token, which the back end does not issue to a reporter yet (TEN-043), so until
// then the back end refuses it and so does this route.

const WORDING = 'v1';

type Body = { subscription?: unknown; consentWordingVersion?: unknown };

export const POST = withBff(
  async (request, session) => {
    const body = (await request.json().catch(() => undefined)) as Body | undefined;
    if (body?.consentWordingVersion !== WORDING || typeof body.subscription !== 'object' || body.subscription === null) {
      return refuse(400, 'invalid');
    }
    const deviceId = await ensureDevice(request);
    const reply = await identityCall(request, {
      method: 'POST',
      path: '/identity/push-subscription',
      body: { subscription: body.subscription, wordingVersion: WORDING, deviceId },
      headers: { Authorization: `Bearer ${session.backendToken}`, 'Idempotency-Key': crypto.randomUUID() },
    });
    if (reply.status === 200) return Response.json({ saved: true }, { headers: { 'Cache-Control': 'no-store' } });
    if (reply.status === 401) return refuse(401, 'no-session');
    return notBuilt();
  },
  { roles: ['reporter'] },
);
