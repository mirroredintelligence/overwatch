import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, routeId } from '@/lib/lead/bffInput';
import { revokedFrom } from '@/lib/screens/admin';
import { json } from '@/lib/screens/answers';

// A shift lead disconnects a wall screen (W9I, TEN-072): POST /screens/{id}/revoke at the back end's
// root. The screen's device token stops at once and the wall token it holds is refused at its next read.
// Lead only, CSRF checked (withBff), the Idempotency-Key passed on so a double press is one revoke. The
// back end needs a JSON body, so an empty one is sent; nothing the browser sent in a body is read. An id
// that is not an id, and an id the back end does not hold (another tenant's included), are the one 404.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const { data } = await fhirFetch<unknown>(`/screens/${encodeURIComponent(id)}/revoke`, {
      method: 'POST',
      root: true,
      token: session.backendToken,
      idempotencyKey: key,
      body: {},
    });
    return json(200, revokedFrom(data));
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
