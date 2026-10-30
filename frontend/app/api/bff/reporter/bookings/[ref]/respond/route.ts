import { withBff } from '@/lib/bff/handler';
import { BOOKING_REFERENCE, parseResponded } from '@/lib/reporter/answers';
import { keyOf, onlyFields, plain, readJson, reporterCall } from '@/lib/reporter/backend';

// POST /api/bff/reporter/bookings/[ref]/respond (W36, W8E). Confirm or decline a booking by the
// four-digit reference, to `POST /reporter/bookings/{reference}/respond` with the screen's
// Idempotency-Key (DEC-822). A booking already answered is the back end's 409. Only the status, and when
// it was confirmed, go back to the browser.
type Context = { params: Promise<{ ref: string }> };

const REASONS = ['full', 'outside-criteria', 'staffing-or-transport', 'other'];

export const POST = withBff(
  async (request, session, context: Context) => {
    const { ref } = await context.params;
    if (!BOOKING_REFERENCE.test(ref)) return plain(404, 'not-found');
    const key = keyOf(request);
    const body = await readJson(request);
    if (key === null || !onlyFields(body, ['decision', 'reason'])) return plain(400, 'invalid');
    const { decision, reason } = body;
    if (decision !== 'confirm' && decision !== 'decline') return plain(400, 'invalid');
    if (reason !== undefined && (decision !== 'decline' || typeof reason !== 'string' || !REASONS.includes(reason))) return plain(400, 'invalid');
    const sent = reason === undefined ? { decision } : { decision, reason };
    return reporterCall(session, `/reporter/bookings/${ref}/respond`, { body: sent, key, parse: parseResponded });
  },
  { idScoped: true, roles: ['reporter'] },
);
