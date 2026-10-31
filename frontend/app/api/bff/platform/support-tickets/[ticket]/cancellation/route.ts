import { withOperatorBff } from '@/lib/operator/bff';
import { parseSupportTicket } from '@/lib/operator/views';
import { NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';

// POST /platform/support-tickets/{ticket}/cancellation: the support person takes a request back, only while
// it is waiting.

type Context = { params: Promise<Record<string, string>> };

const post = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'ticket', 'ticket');
    const data = await tenantWrite(session, request, 'POST', `/platform/support-tickets/${id}/cancellation`, {});
    return Response.json(parseSupportTicket(data), { headers: NO_STORE });
  },
  { roles: ['support'], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
