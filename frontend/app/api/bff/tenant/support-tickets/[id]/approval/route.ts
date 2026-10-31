import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseTicketApproval } from '@/lib/tenantAdmin/views';

// POST /tenant/support-tickets/{id}/approval: approves the request. The one-time code is in the answer and is shown once to the administrator, who gives it to the support person: it is never stored or cached, and a lost answer is handled by revoking and asking again.

type Context = { params: Promise<Record<string, string>> };

const handle = withBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'ticket');
    const data = await tenantWrite(session, request, 'POST', `/tenant/support-tickets/${id}/approval`, {});
    return Response.json(parseTicketApproval(data), { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], idScoped: true },
);

export const POST = (request: Request, context: Context) => handle(request, context);
