import { withBff } from '@/lib/bff/handler';
import { OFFER_ID, parseAnswer } from '@/lib/practitioner/answers';
import { keyOf, onlyFields, plain, readJson, reporterCall } from '@/lib/reporter/backend';

// POST /api/bff/practitioner/visits/[id]/decline (DEC-1306 to DEC-1309). Declines this person's offer
// only, with the screen's Idempotency-Key. It takes no reason and sends nothing about the person.
type Context = { params: Promise<{ id: string }> };

export const POST = withBff(
  async (request, session, context: Context) => {
    const { id } = await context.params;
    if (!OFFER_ID.test(id)) return plain(404, 'not-found');
    const key = keyOf(request);
    const body = await readJson(request);
    if (key === null || !onlyFields(body, [])) return plain(400, 'invalid');
    return reporterCall(session, `/practitioner/visits/${id}/decline`, { body: {}, key, parse: parseAnswer });
  },
  { idScoped: true, roles: ['reporter'] },
);
