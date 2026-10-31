import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseTicket } from '@/lib/tenantAdmin/views';

// DELETE /tenant/support-tickets/{id}/access: takes back an approved code, or ends an open access at once.

type Context = { params: Promise<Record<string, string>> };

const handle = withBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'ticket');
    const data = await tenantWrite(session, request, 'DELETE', `/tenant/support-tickets/${id}/access`);
    return Response.json(parseTicket(data), { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], idScoped: true },
);

export const DELETE = (request: Request, context: Context) => handle(request, context);
