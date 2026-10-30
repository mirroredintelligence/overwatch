import { withBff } from '@/lib/bff/handler';
import { notBuilt, ownService, refuse } from '@/lib/reporter/bff';

// POST /api/bff/reporter/services/[serviceId]/accept (W38). Ownership first, then the answer's
// shape. The back end has no reporter accept route yet: not-built.
type Context = { params: Promise<{ serviceId: string }> };

export const POST = withBff(
  async (request, session, context: Context) => {
    const { serviceId } = await (context as unknown as Context).params;
    const owned = ownService(session, serviceId);
    if (owned !== null) return owned;
    const body = (await request.json().catch(() => undefined)) as { accept?: unknown } | undefined;
    if (typeof body?.accept !== 'boolean') return refuse(400, 'invalid');
    return notBuilt();
  },
  { roles: ['reporter'] },
);
