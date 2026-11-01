import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseMemberChange } from '@/lib/tenantAdmin/views';

// DELETE /tenant/groups/{group}/members/{user}: removes a person from one of the groups Overwatch made, by the id the
// list showed. The same checks as an add: the back end decides which groups, not the browser.

type Context = { params: Promise<Record<string, string>> };

const handle = withBff<Context>(
  async (request, session, context) => {
    const group = await segment(context, 'group', 'guid');
    const user = await segment(context, 'user', 'guid');
    const data = await tenantWrite(session, request, 'DELETE', `/tenant/groups/${group}/members/${user}`);
    return Response.json(parseMemberChange(data), { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], idScoped: true },
);

export const DELETE = (request: Request, context: Context) => handle(request, context);
