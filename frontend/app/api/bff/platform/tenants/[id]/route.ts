import { createTenantBody } from '@/lib/operator/bodies';
import { withOperatorBff } from '@/lib/operator/bff';
import { jsonBody, NO_STORE, tenantRead, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseCreated, parseTenantDetail } from '@/lib/operator/views';

// GET /platform/tenants/{id}: the tenant's record, host, numbers and what activation waits for (the
// operator's). PUT creates it (201), or finishes a creation that stopped (200). The tenant is the path's.

type Context = { params: Promise<Record<string, string>> };

const get = withOperatorBff<Context>(
  async (_request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    return Response.json(parseTenantDetail(await tenantRead(session, `/platform/tenants/${id}`)), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

const put = withOperatorBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    const body = createTenantBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'PUT', `/platform/tenants/${id}`, body);
    const created = parseCreated(data);
    return Response.json(created, { status: created.created ? 201 : 200, headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
export const PUT = (request: Request, context: Context) => put(request, context);
