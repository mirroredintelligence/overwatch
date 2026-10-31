import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { parseOverview } from '@/lib/tenantAdmin/views';

// GET /tenant/overview for the tenant administrator (TEN-076). The answer is read into the fields a screen shows.

const get = withBff(
  async (_request, session) => Response.json(parseOverview(await tenantRead(session, '/tenant/overview')), { headers: NO_STORE }),
  { roles: ['tenant-admin'] },
);

export const GET = (request: Request) => get(request, undefined);
