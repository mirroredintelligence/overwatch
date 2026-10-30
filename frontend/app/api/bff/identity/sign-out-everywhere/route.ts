import { randomUUID } from 'node:crypto';
import { clearCsrf } from '@/lib/auth/csrf';
import { destroySession } from '@/lib/auth/session';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';

// POST /api/bff/identity/sign-out-everywhere (W55, W8E). The back end's route (R13) ends every session
// of the signed-in person and revokes their devices. It takes the reporter's token like every other
// call. This phone's own session ends here too, so it never depends on the page asking again; a
// failure at the back end leaves the session as it was. The count is the back end's, or 0.
export const POST = withBff(
  async (_request, session) => {
    const { data } = await fhirFetch<{ signedOut?: unknown } | undefined>('/identity/sign-out-everywhere', {
      method: 'POST',
      token: session.backendToken,
      root: true,
      body: {},
      idempotencyKey: randomUUID(),
    });
    await destroySession();
    await clearCsrf();
    const signedOut = data?.signedOut;
    return Response.json({ signedOut: typeof signedOut === 'number' ? signedOut : 0 });
  },
  { roles: ['reporter'] },
);
