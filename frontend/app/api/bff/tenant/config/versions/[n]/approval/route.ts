import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseVersionApproval } from '@/lib/tenantAdmin/views';

// POST /tenant/config/versions/{n}/approval: one approval of the signed-in person. The author of a clinical
// change and a repeat approver are refused by the back end; the approval that completes it makes it current.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const n = await segment(context, 'n', 'version');
    const data = await tenantWrite(session, request, 'POST', `/tenant/config/versions/${n}/approval`, {});
    return Response.json(parseVersionApproval(data), { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
