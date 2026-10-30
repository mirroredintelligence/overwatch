import { withBff } from '@/lib/bff/handler';
import { notBuilt, ownService, refuse } from '@/lib/reporter/bff';
import { isUkMobile } from '@/lib/forms/ukMobile';

// POST /api/bff/reporter/services/[serviceId]/cover (W38). Ownership, the mobile number's shape, and
// the until choice are checked here. The back end has no reporter cover route yet: not-built.
type Context = { params: Promise<{ serviceId: string }> };
type Body = { phone?: unknown; until?: unknown; date?: unknown };

const UNTIL = ['tonight', 'this-week', 'date'];

export const POST = withBff(
  async (request, session, context: Context) => {
    const { serviceId } = await (context as unknown as Context).params;
    const owned = ownService(session, serviceId);
    if (owned !== null) return owned;
    const body = (await request.json().catch(() => undefined)) as Body | undefined;
    if (typeof body?.phone !== 'string' || !isUkMobile(body.phone)) return refuse(400, 'invalid');
    if (typeof body.until !== 'string' || !UNTIL.includes(body.until)) return refuse(400, 'invalid');
    if (body.until === 'date' && (typeof body.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(body.date))) {
      return refuse(400, 'invalid');
    }
    return notBuilt();
  },
  { roles: ['reporter'] },
);
