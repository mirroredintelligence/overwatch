import { withBff } from '@/lib/bff/handler';
import { SERVICE_ID, parsePrompt } from '@/lib/reporter/answers';
import { plain, reporterCall } from '@/lib/reporter/backend';

// GET /api/bff/reporter/services/[serviceId]/prompt (W35, W8E). What is on record, the usual range and
// when to reply by. A service the reporter does not hold is the back end's one 404, the same as one that
// does not exist or is another tenant's (H-452); the BFF does not decide it from the cookie.
type Context = { params: Promise<{ serviceId: string }> };

export const GET = withBff(
  async (_request, session, context: Context) => {
    const { serviceId } = await context.params;
    if (!SERVICE_ID.test(serviceId)) return plain(404, 'not-found');
    return reporterCall(session, `/reporter/services/${serviceId}/prompt`, { parse: parsePrompt });
  },
  { idScoped: true, roles: ['reporter'] },
);
