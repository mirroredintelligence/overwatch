import { withOperatorBff } from '@/lib/operator/bff';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseConsent } from '@/lib/operator/views';

// GET /platform/tenants/{id}/admin-consent: the tenant's latest admin consent invitation (DEC-1316): the
// masked address, pending / consented / expired / revoked, and the reason in words. The address is never here.

type Context = { params: Promise<Record<string, string>> };

const handle = withOperatorBff<Context>(
  async (_request, session, context) => {
    const id = await segment(context, 'id', 'tenant');
    return Response.json(parseConsent(await tenantRead(session, `/platform/tenants/${id}/admin-consent`)), { headers: NO_STORE });
  },
  { roles: ['platform-operator'], idScoped: true },
);

export const GET = (request: Request, context: Context) => handle(request, context);
