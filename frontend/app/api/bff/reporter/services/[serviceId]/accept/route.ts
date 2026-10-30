import { withBff } from '@/lib/bff/handler';
import { SERVICE_ID, parseAccepted } from '@/lib/reporter/answers';
import { onlyFields, plain, readJson, reporterCall } from '@/lib/reporter/backend';

// POST /api/bff/reporter/services/[serviceId]/accept (W38, W8E). Yes or no to a service the shift lead
// added (DEC-823): yes is recorded and changes no post, no ends the reporter's own post on it now. Only
// a post the reporter owns can be answered (the back end's one 404 otherwise).
type Context = { params: Promise<{ serviceId: string }> };

export const POST = withBff(
  async (request, session, context: Context) => {
    const { serviceId } = await context.params;
    if (!SERVICE_ID.test(serviceId)) return plain(404, 'not-found');
    const body = await readJson(request);
    if (!onlyFields(body, ['accept']) || typeof body.accept !== 'boolean') return plain(400, 'invalid');
    return reporterCall(session, `/reporter/services/${serviceId}/accept`, { body: { accept: body.accept }, parse: parseAccepted });
  },
  { idScoped: true, roles: ['reporter'] },
);
