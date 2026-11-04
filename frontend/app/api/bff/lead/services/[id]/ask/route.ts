import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, routeId } from '@/lib/lead/bffInput';

// Asks a service for its capacity figure now (DEC-1335): the back end queues the request to be sent at once,
// and records it as the open question so the reply matches it. Lead only, CSRF checked on every POST, and the
// Idempotency-Key is passed on, so a double press asks once. The back end answers 409 when a request is already
// due or the service is not active; that answer is passed on, not turned into a success.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const { data } = await fhirFetch<{ dueAt?: unknown }>(`/lead/services/${encodeURIComponent(id)}/ask`, {
      method: 'POST',
      root: true,
      token: session.backendToken,
      idempotencyKey: key,
    });
    return Response.json({ queued: true, dueAt: typeof data?.dueAt === 'string' ? data.dueAt : null }, {
      headers: { 'Cache-Control': 'no-store' },
    });
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
