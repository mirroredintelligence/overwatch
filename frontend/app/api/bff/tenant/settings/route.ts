import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { parseSettings } from '@/lib/tenantAdmin/views';

// GET /tenant/settings for the tenant administrator (TEN-076). The answer is read into the fields a screen shows.

const get = withBff(
  async (_request, session) => Response.json(parseSettings(await tenantRead(session, '/tenant/settings')), { headers: NO_STORE }),
  { roles: ['tenant-admin'] },
);

export const GET = (request: Request) => get(request, undefined);
