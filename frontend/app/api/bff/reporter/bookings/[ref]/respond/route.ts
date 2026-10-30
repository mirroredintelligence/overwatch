import { FhirError, fhirFetch } from '@/lib/fhir/client';
import { refuse } from '@/lib/reporter/bff';
import { withBff } from '@/lib/bff/handler';
import { toBffError } from '@/lib/bff/errors';

// POST /api/bff/reporter/bookings/[ref]/respond (W36). Maps the decision to the back end's
// `$respond` on the booking Task (R09) as a Parameters body, with the reporter's bearer and the
// screen's Idempotency-Key. Only the status goes back to the browser. The reference is passed as
// the Task id: the reference-to-id mapping for reporters is not built (see the W36 fragment).

type Context = { params: Promise<{ ref: string }> };
type Body = { decision?: unknown; reason?: unknown };

const REASONS = ['full', 'outside-criteria', 'staffing-or-transport', 'other'];
const KEY = /^[A-Za-z0-9-]{8,64}$/;
const NO_STORE = { 'Cache-Control': 'no-store' };

export const POST = withBff(
  async (request, session, context: Context) => {
    const { ref } = await (context as unknown as Context).params;
    const key = request.headers.get('Idempotency-Key') ?? '';
    if (!KEY.test(key)) return refuse(400, 'invalid');

    const body = (await request.json().catch(() => undefined)) as Body | undefined;
    const decision = body?.decision;
    if (decision !== 'confirm' && decision !== 'decline') return refuse(400, 'invalid');
    if (body?.reason !== undefined && (decision !== 'decline' || typeof body.reason !== 'string' || !REASONS.includes(body.reason))) {
      return refuse(400, 'invalid');
    }

    const parameter: { name: string; valueCode: string }[] = [{ name: 'decision', valueCode: decision }];
    if (typeof body?.reason === 'string') parameter.push({ name: 'reason', valueCode: body.reason });

    try {
      await fhirFetch(`/Task/${encodeURIComponent(ref)}/$respond`, {
        method: 'POST',
        body: { resourceType: 'Parameters', parameter },
        token: session.backendToken,
        idempotencyKey: key,
      });
    } catch (error) {
      if (error instanceof FhirError && error.status === 401) return refuse(401, 'no-session');
      return toBffError(error);
    }
    return Response.json({ status: decision === 'confirm' ? 'confirmed' : 'declined' }, { headers: NO_STORE });
  },
  { roles: ['reporter'] },
);
