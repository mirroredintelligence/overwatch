import { withBff } from '@/lib/bff/handler';
import { BOOKING_REFERENCE, parseBooking } from '@/lib/reporter/answers';
import { plain, reporterCall } from '@/lib/reporter/backend';

// GET /api/bff/reporter/bookings/[ref] (W36, W8E). The booking by the four-digit reference the
// notification carries, as the back end maps it (DEC-821): for a service the reporter holds, with the
// age band, the need, the urgency and the reply-by time, never the case, the postcode, the requester or
// the Task id. A reference that is not four digits, unknown, another tenant's or for another service is
// the one 404.
type Context = { params: Promise<{ ref: string }> };

export const GET = withBff(
  async (_request, session, context: Context) => {
    const { ref } = await context.params;
    if (!BOOKING_REFERENCE.test(ref)) return plain(404, 'not-found');
    return reporterCall(session, `/reporter/bookings/${ref}`, { parse: parseBooking });
  },
  { idScoped: true, roles: ['reporter'] },
);
