import { withBff } from '@/lib/bff/handler';
import { notBuilt, ownService, refuse } from '@/lib/reporter/bff';

// POST /api/bff/reporter/services/[serviceId]/report (W35). Checks the body's shape and the
// service's ownership, then answers not-built: the back end has no reporter report route (the
// capacity report needs the capacity profile, and a confirm is the link's own route).
type Context = { params: Promise<{ serviceId: string }> };
type Body = { kind?: unknown; value?: unknown; confirmOutOfRange?: unknown };

const KINDS = ['confirm', 'number', 'closed'];

export const POST = withBff(
  async (request, session, context: Context) => {
    const { serviceId } = await (context as unknown as Context).params;
    const owned = ownService(session, serviceId);
    if (owned !== null) return owned;
    const body = (await request.json().catch(() => undefined)) as Body | undefined;
    if (typeof body?.kind !== 'string' || !KINDS.includes(body.kind)) return refuse(400, 'invalid');
    if (body.kind === 'number' && (!Number.isInteger(body.value) || (body.value as number) < 0 || (body.value as number) > 999)) {
      return refuse(400, 'invalid');
    }
    return notBuilt();
  },
  { roles: ['reporter'] },
);
