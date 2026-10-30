import { withBff } from '@/lib/bff/handler';
import { notBuilt, refuse } from '@/lib/reporter/bff';
import { isUkMobile } from '@/lib/forms/ukMobile';

// POST /api/bff/reporter/cover (W37). The phone number's shape is checked here; the back end has no
// reporter cover route (the lead's change-number route is for leads), so a valid cover is not-built.
export const POST = withBff(
  async (request) => {
    const body = (await request.json().catch(() => undefined)) as { phone?: unknown } | undefined;
    if (typeof body?.phone !== 'string' || !isUkMobile(body.phone)) return refuse(400, 'invalid');
    return notBuilt();
  },
  { roles: ['reporter'] },
);
