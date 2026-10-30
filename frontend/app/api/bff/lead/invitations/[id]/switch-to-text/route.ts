import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, routeId } from '@/lib/lead/bffInput';

// Switches an invited reporter to text (W43): the back end's switch (U25/U24), with the Idempotency-Key passed on.
// Lead only, CSRF. A reporter with no number held is a 409 from the back end. The answer names the channel.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const { data } = await fhirFetch<{ channel?: unknown }>(`/lead/invitations/${encodeURIComponent(id)}/switch-to-text`, {
      method: 'POST',
      root: true,
      token: session.backendToken,
      idempotencyKey: key,
    });
    return Response.json({ channel: data.channel }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
