import { withBff } from '@/lib/bff/handler';
import { notBuilt, refuse } from '@/lib/reporter/bff';
import { identityCall } from '@/lib/reporter/identity';

// POST /api/bff/identity/sign-out-everywhere (W55). The back end's route (R13) signs out every phone
// of the signed-in person. It needs the reporter's bearer token, which the back end does not issue
// to a reporter yet (TEN-043): until then the back end refuses it, and so does this route.
export const POST = withBff(
  async (request, session) => {
    const reply = await identityCall(request, {
      method: 'POST',
      path: '/identity/sign-out-everywhere',
      headers: { Authorization: `Bearer ${session.backendToken}`, 'Idempotency-Key': crypto.randomUUID() },
      body: {},
    });
    if (reply.status === 200) {
      const signedOut = (reply.body as { signedOut?: unknown } | undefined)?.signedOut;
      return Response.json({ signedOut: typeof signedOut === 'number' ? signedOut : 0 }, { headers: { 'Cache-Control': 'no-store' } });
    }
    if (reply.status === 401) return refuse(401, 'no-session');
    return notBuilt();
  },
  { roles: ['reporter'] },
);
