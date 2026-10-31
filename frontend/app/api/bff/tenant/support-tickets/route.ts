import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { parseTickets } from '@/lib/tenantAdmin/views';

// GET /tenant/support-tickets for the tenant administrator (TEN-076). The answer is read into the fields a screen shows.

const get = withBff(
  async (_request, session) => Response.json(parseTickets(await tenantRead(session, '/tenant/support-tickets')), { headers: NO_STORE }),
  { roles: ['tenant-admin'] },
);

export const GET = (request: Request) => get(request, undefined);
