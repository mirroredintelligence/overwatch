import { withOperatorBff } from '@/lib/operator/bff';
import { offboardingBody } from '@/lib/operator/bodies';
import { parseOffboarding } from '@/lib/operator/views';
import { jsonBody, NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';

// POST /platform/tenants/{id}/offboarding: starts closing a tenant. The operator types the tenant's own id
// (`confirm`), which must be the path's; the back end gets it as `confirmTenantId`. The tenant is closed at
// the edge from now (known issue W9C-K2): the dialog says so before this is called.

type Context = { params: Promise<Record<string, string>> };

const post = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = offboardingBody(await jsonBody(request), id);
    const data = await tenantWrite(session, request, 'POST', `/platform/tenants/${id}/offboarding`, body);
    return Response.json(parseOffboarding(data), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
