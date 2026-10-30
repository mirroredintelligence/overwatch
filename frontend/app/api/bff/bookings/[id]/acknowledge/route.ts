import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';
import { acknowledgeBooking } from '@/lib/advisor/bookingServer';

// The advisor has seen a withdrawal or a not-reached report (W21). Acknowledging twice is fine; the
// back end stops the shift lead's escalation.

const NO_STORE = { 'Cache-Control': 'no-store' };
const BOOKING_ID = /^[A-Za-z0-9-]{1,64}$/;
const KEY = /^[A-Za-z0-9-]{16,80}$/;

type Context = { params: Promise<{ id: string }> };

const post = withBff<Context>(
  async (request, session, context) => {
    const { id } = await context.params;
    if (!BOOKING_ID.test(id)) return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    const key = request.headers.get('idempotency-key');
    if (key === null || !KEY.test(key)) return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    await acknowledgeBooking(session, id, key);
    return Response.json({ acknowledged: true }, { status: 200, headers: NO_STORE });
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
