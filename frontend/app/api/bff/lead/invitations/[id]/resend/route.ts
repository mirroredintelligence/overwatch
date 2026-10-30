import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, routeId } from '@/lib/lead/bffInput';

// Sends an invitation again (W43): the back end's resend (U24), with the Idempotency-Key passed on, so a double press
// sends once. Lead only, CSRF. The answer names the ids and when the link expires, never the number.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const { data } = await fhirFetch<{ invitationId?: unknown; registrationId?: unknown; expiresAt?: unknown }>(
      `/lead/invitations/${encodeURIComponent(id)}/resend`,
      { method: 'POST', root: true, token: session.backendToken, idempotencyKey: key },
    );
    return Response.json(
      { invitationId: data.invitationId, registrationId: data.registrationId, expiresAt: data.expiresAt },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
