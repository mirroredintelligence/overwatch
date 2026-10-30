import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, routeId } from '@/lib/lead/bffInput';

// Asks a service for its figure again (W17): the back end sends the reminder the ladder is waiting to send and
// answers 409 when none is waiting. Lead only, CSRF checked on every POST (withBff), and the Idempotency-Key is
// passed on, so a double press sends once. Nothing of the reporter's number is returned.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    await fhirFetch<unknown>(`/lead/services/${encodeURIComponent(id)}/remind`, {
      method: 'POST',
      root: true,
      token: session.backendToken,
      idempotencyKey: key,
    });
    return Response.json({ reminded: true }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
