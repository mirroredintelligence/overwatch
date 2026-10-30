import { withBff } from '@/lib/bff/handler';
import { notBuilt, ownService } from '@/lib/reporter/bff';

// GET /api/bff/reporter/services/[serviceId]/prompt (W35). A service the reporter does not act for
// is the same 404 as one that does not exist. The back end has no reporter prompt route yet.
type Context = { params: Promise<{ serviceId: string }> };

export const GET = withBff(async (_request, session, context: Context) => {
  const { serviceId } = await (context as unknown as Context).params;
  return ownService(session, serviceId) ?? notBuilt();
}, { idScoped: true, roles: ['reporter'] });
