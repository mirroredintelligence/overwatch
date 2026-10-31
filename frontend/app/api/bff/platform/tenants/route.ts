import { withOperatorBff } from '@/lib/operator/bff';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { parseTenantList } from '@/lib/operator/views';

// GET /platform/tenants for the operator (the type, the address, the activation date) and for a support
// person (the id, the name and the status only). What a support person must not see is dropped here even if
// the back end sent it.

const get = withOperatorBff(
  async (_request, session) => Response.json(parseTenantList(await tenantRead(session, '/platform/tenants'), session.role), { headers: NO_STORE }),
);

export const GET = (request: Request) => get(request, undefined);
