import { withBff } from '@/lib/bff/handler';
import { OFFER_ID, parseVisit } from '@/lib/practitioner/answers';
import { plain, reporterCall } from '@/lib/reporter/backend';

// GET /api/bff/practitioner/visits/[id] (DEC-1306 to DEC-1309). One offer or visit made to the signed-in
// person. An offer shows what is needed, the area sector and the time; the address and contact come only
// once the visit is accepted and only to the person it was offered to. An id that is not the person's, is
// another tenant's or is unknown is the one 404.
type Context = { params: Promise<{ id: string }> };

export const GET = withBff(
  async (_request, session, context: Context) => {
    const { id } = await context.params;
    if (!OFFER_ID.test(id)) return plain(404, 'not-found');
    return reporterCall(session, `/practitioner/visits/${id}`, { parse: parseVisit });
  },
  { idScoped: true, roles: ['reporter'] },
);
