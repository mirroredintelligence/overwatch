import { withOperatorBff } from '@/lib/operator/bff';
import { entraGroupsBody } from '@/lib/operator/bodies';
import { NO_STORE, jsonBody, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseGroupsMade } from '@/lib/operator/views';

// POST /platform/tenants/{id}/entra-groups: makes the organisation's groups in its own directory, gives each the
// Overwatch role there and maps it to its role here (DEC-1317). Needs the administrator's consent. The names are the
// back end's, built from the organisation's code: the body holds only which roles to give a group. Safe to repeat.

type Context = { params: Promise<Record<string, string>> };

const handle = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = entraGroupsBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', `/platform/tenants/${id}/entra-groups`, body);
    return Response.json(parseGroupsMade(data), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const POST = (request: Request, context: Context) => handle(request, context);
