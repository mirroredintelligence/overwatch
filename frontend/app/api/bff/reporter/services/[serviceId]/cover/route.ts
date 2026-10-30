import { withBff } from '@/lib/bff/handler';
import { SERVICE_ID, parseCover } from '@/lib/reporter/answers';
import { plain, readJson, reporterCall } from '@/lib/reporter/backend';
import { coverBody } from '@/lib/reporter/cover';

// POST /api/bff/reporter/services/[serviceId]/cover (W38, W8E). The same for one service (DEC-820): only
// that post moves. A post the reporter only covers cannot be passed on (the back end's 404, H-456).
type Context = { params: Promise<{ serviceId: string }> };

export const POST = withBff(
  async (request, session, context: Context) => {
    const { serviceId } = await context.params;
    if (!SERVICE_ID.test(serviceId)) return plain(404, 'not-found');
    const body = coverBody(await readJson(request));
    if (body === null) return plain(400, 'invalid');
    return reporterCall(session, `/reporter/services/${serviceId}/cover`, { body, parse: parseCover });
  },
  { idScoped: true, roles: ['reporter'] },
);
