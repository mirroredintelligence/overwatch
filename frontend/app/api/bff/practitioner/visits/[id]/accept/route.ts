import { withBff } from '@/lib/bff/handler';
import { OFFER_ID, parseAnswer } from '@/lib/practitioner/answers';
import { keyOf, onlyFields, plain, readJson, reporterCall } from '@/lib/reporter/backend';

// POST /api/bff/practitioner/visits/[id]/accept (DEC-1306 to DEC-1309). Accepts the offer, with the
// screen's Idempotency-Key. The back end confirms the booking once, so a second person's accept is its
// 409 ("no longer open"). The answer is the visit's id and state; the details are read on the visit page.
type Context = { params: Promise<{ id: string }> };

export const POST = withBff(
  async (request, session, context: Context) => {
    const { id } = await context.params;
    if (!OFFER_ID.test(id)) return plain(404, 'not-found');
    const key = keyOf(request);
    const body = await readJson(request);
    if (key === null || !onlyFields(body, [])) return plain(400, 'invalid');
    return reporterCall(session, `/practitioner/visits/${id}/accept`, { body: {}, key, parse: parseAnswer });
  },
  { idScoped: true, roles: ['reporter'] },
);
