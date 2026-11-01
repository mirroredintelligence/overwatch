import { withBff } from '@/lib/bff/handler';
import { memberBody } from '@/lib/tenantAdmin/bodies';
import { NO_STORE, jsonBody, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseMemberChange } from '@/lib/tenantAdmin/views';

// POST /tenant/groups/{group}/members: adds a person, by address, to one of the groups Overwatch made. The group is
// the path's and is only an id: the back end checks it against its own mappings and the directory's name for it
// (the organisation's prefix), never against anything the browser says. The address is not echoed.

type Context = { params: Promise<Record<string, string>> };

const handle = withBff<Context>(
  async (request, session, context) => {
    const group = await segment(context, 'group', 'guid');
    const body = memberBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/tenant/groups/${group}/members`, body);
    return Response.json(parseMemberChange(data), { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], idScoped: true },
);

export const POST = (request: Request, context: Context) => handle(request, context);
