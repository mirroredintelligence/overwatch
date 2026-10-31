import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseTicket } from '@/lib/tenantAdmin/views';

// POST /tenant/support-tickets/{id}/refusal: refuses the request.

type Context = { params: Promise<Record<string, string>> };

const handle = withBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'ticket');
    const data = await tenantWrite(session, request, 'POST', `/tenant/support-tickets/${id}/refusal`, {});
    return Response.json(parseTicket(data), { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], idScoped: true },
);

export const POST = (request: Request, context: Context) => handle(request, context);
