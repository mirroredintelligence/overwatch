import { withBff } from '@/lib/bff/handler';
import { notBuilt, refuse } from '@/lib/reporter/bff';

// POST /api/bff/reporter/reports/batch (W38). Each item must be a confirm for a service the reporter
// acts for; anything else is refused before the back end is asked. The back end has no reporter
// batch route yet, so a valid batch is not-built.
type Item = { serviceId?: unknown; kind?: unknown };

export const POST = withBff(
  async (request, session) => {
    const body = (await request.json().catch(() => undefined)) as { items?: unknown } | undefined;
    if (!Array.isArray(body?.items) || body.items.length < 1 || body.items.length > 10) return refuse(400, 'invalid');
    for (const item of body.items as Item[]) {
      if (item.kind !== 'confirm' || typeof item.serviceId !== 'string') return refuse(400, 'invalid');
      if (!session.services.includes(item.serviceId)) return refuse(404, 'not-found');
    }
    return notBuilt();
  },
  { roles: ['reporter'] },
);
