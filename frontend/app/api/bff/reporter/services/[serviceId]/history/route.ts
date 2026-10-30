import { withBff } from '@/lib/bff/handler';
import { notBuilt, ownService } from '@/lib/reporter/bff';

// GET /api/bff/reporter/services/[serviceId]/history?day=today (W35). Same ownership check as the
// prompt. The back end's latest-report route gives one report, not a day's list: not-built.
type Context = { params: Promise<{ serviceId: string }> };

export const GET = withBff(async (_request, session, context: Context) => {
  const { serviceId } = await (context as unknown as Context).params;
  return ownService(session, serviceId) ?? notBuilt();
}, { idScoped: true, roles: ['reporter'] });
