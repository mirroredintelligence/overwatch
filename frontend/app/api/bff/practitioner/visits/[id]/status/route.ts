import { withBff } from '@/lib/bff/handler';
import { OFFER_ID, parseAnswer, PRACTITIONER_STATUSES } from '@/lib/practitioner/answers';
import { keyOf, onlyFields, plain, readJson, reporterCall } from '@/lib/reporter/backend';

// POST /api/bff/practitioner/visits/[id]/status (DEC-1306 to DEC-1309). The status list of an accepted
// visit: on my way, arrived, done, could not reach the patient, with the screen's Idempotency-Key. While
// on the way the person may add an estimated arrival in minutes (1 to 240), which the back end accepts only
// if they chose to share it. A position is never accepted: only `status` and `etaMinutes` pass.
type Context = { params: Promise<{ id: string }> };

export const POST = withBff(
  async (request, session, context: Context) => {
    const { id } = await context.params;
    if (!OFFER_ID.test(id)) return plain(404, 'not-found');
    const key = keyOf(request);
    const body = await readJson(request);
    if (key === null || !onlyFields(body, ['status', 'etaMinutes'])) return plain(400, 'invalid');
    const { status, etaMinutes } = body;
    if (typeof status !== 'string' || !(PRACTITIONER_STATUSES as readonly string[]).includes(status)) return plain(400, 'invalid');
    if (etaMinutes !== undefined) {
      if (status !== 'on-my-way' || typeof etaMinutes !== 'number' || !Number.isInteger(etaMinutes) || etaMinutes < 1 || etaMinutes > 240) return plain(400, 'invalid');
    }
    const sent = etaMinutes === undefined ? { status } : { status, etaMinutes };
    return reporterCall(session, `/practitioner/visits/${id}/status`, { body: sent, key, parse: parseAnswer });
  },
  { idScoped: true, roles: ['reporter'] },
);
