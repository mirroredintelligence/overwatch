import { withOperatorBff } from '@/lib/operator/bff';
import { groupMemberBody } from '@/lib/operator/bodies';
import { NO_STORE, jsonBody, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseMemberAdded } from '@/lib/operator/views';

// POST /platform/tenants/{id}/entra-groups/members: adds a first member to one of the organisation's groups, by role
// and the person's work address, which the back end looks up in the organisation's directory (DEC-1317). The address
// is not echoed, stored or logged, and no group id comes from the browser.

type Context = { params: Promise<Record<string, string>> };

const handle = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = groupMemberBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/platform/tenants/${id}/entra-groups/members`, body);
    return Response.json(parseMemberAdded(data), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const POST = (request: Request, context: Context) => handle(request, context);
