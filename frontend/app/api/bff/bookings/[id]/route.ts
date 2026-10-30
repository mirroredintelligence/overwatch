import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';
import { readBooking } from '@/lib/advisor/bookingServer';

// The advisor's read of one booking (W20). The answer is the booking's state only, never the Task.

const NO_STORE = { 'Cache-Control': 'no-store' };
const BOOKING_ID = /^[A-Za-z0-9-]{1,64}$/;

type Context = { params: Promise<{ id: string }> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!BOOKING_ID.test(id)) return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    return Response.json(await readBooking(session, id), { headers: NO_STORE });
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
