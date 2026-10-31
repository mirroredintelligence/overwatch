import { withOperatorBff } from '@/lib/operator/bff';
import { parseSupportTickets } from '@/lib/operator/views';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';

// GET /platform/support-tickets: the support person's own requests, newest first.

const get = withOperatorBff(
  async (_request, session) => Response.json(parseSupportTickets(await tenantRead(session, '/platform/support-tickets')), { headers: NO_STORE }),
  { roles: ['support'] },
);

export const GET = (request: Request) => get(request, undefined);
