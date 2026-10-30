import { withBff } from '@/lib/bff/handler';
import { SERVICE_ID, parseHistory } from '@/lib/reporter/answers';
import { plain, reporterCall } from '@/lib/reporter/backend';

// GET /api/bff/reporter/services/[serviceId]/history?day=today (W35, W8E). The day's reports, newest
// first. Only `day=today` exists (DEC-817); any other query is refused before the back end.
type Context = { params: Promise<{ serviceId: string }> };

export const GET = withBff(
  async (request, session, context: Context) => {
    const { serviceId } = await context.params;
    if (!SERVICE_ID.test(serviceId)) return plain(404, 'not-found');
    const query = new URL(request.url).searchParams;
    const keys = [...query.keys()];
    if (keys.length !== 1 || keys[0] !== 'day' || query.getAll('day').length !== 1 || query.get('day') !== 'today') return plain(400, 'invalid');
    return reporterCall(session, `/reporter/services/${serviceId}/history?day=today`, { parse: parseHistory });
  },
  { idScoped: true, roles: ['reporter'] },
);
