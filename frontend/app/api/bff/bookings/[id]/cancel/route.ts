import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';
import { FhirError } from '@/lib/fhir/client';
import { CANCEL_REASONS } from '@/lib/advisor/bookings';
import { cancelBooking, readBooking } from '@/lib/advisor/bookingServer';

// The advisor's cancel of a booking (W21). The body names one of the four reasons and nothing else:
// no tenant, organisation or scope (DEC-130). A 409 means the booking moved on before the cancel, so
// the answer carries the status it now has.

const NO_STORE = { 'Cache-Control': 'no-store' };
const BOOKING_ID = /^[A-Za-z0-9-]{1,64}$/;
const KEY = /^[A-Za-z0-9-]{16,80}$/;
const REASONS: readonly string[] = CANCEL_REASONS.map((reason) => reason.code);

type Context = { params: Promise<{ id: string }> };

function refuse(status: number, code: string): Response {
  return Response.json({ code }, { status, headers: NO_STORE });
}

const post = withBff<Context>(
  async (request, session, context) => {
    const { id } = await context.params;
    if (!BOOKING_ID.test(id)) return refuse(400, 'invalid');
    const key = request.headers.get('idempotency-key');
    if (key === null || !KEY.test(key)) return refuse(400, 'invalid');

    let parsed: unknown;
    try {
      parsed = (await request.json()) as unknown;
    } catch {
      return refuse(400, 'invalid');
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return refuse(400, 'invalid');
    const body = parsed as Record<string, unknown>;
    if (!Object.keys(body).every((field) => field === 'reason')) return refuse(400, 'invalid');
    if (typeof body.reason !== 'string' || !REASONS.includes(body.reason)) return refuse(400, 'invalid');

    try {
      const booking = await cancelBooking(session, id, body.reason, key);
      return Response.json({ status: booking.status }, { status: 200, headers: NO_STORE });
    } catch (error) {
      if (!(error instanceof FhirError && error.status === 409)) throw error;
      const now = await readBooking(session, id);
      return Response.json({ code: 'state-changed', status: now.status }, { status: 409, headers: NO_STORE });
    }
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
