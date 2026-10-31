import { withOperatorBff } from '@/lib/operator/bff';
import { parseSupportTicket } from '@/lib/operator/views';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';

// GET /platform/support-tickets/{ticket}: one of the support person's own requests.

type Context = { params: Promise<Record<string, string>> };

const get = withOperatorBff<Context>(
  async (_request, session, context) => {
    const id = await segment(context, 'ticket', 'ticket');
    return Response.json(parseSupportTicket(await tenantRead(session, `/platform/support-tickets/${id}`)), { headers: NO_STORE });
  },
  { roles: ['support'], idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
