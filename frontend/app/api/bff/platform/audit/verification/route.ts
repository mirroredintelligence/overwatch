import { withOperatorBff } from '@/lib/operator/bff';
import { parseIntact } from '@/lib/operator/views';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';

// GET /platform/audit/verification: walks the whole chain and says whether it is intact.

const get = withOperatorBff(
  async (_request, session) => Response.json(parseIntact(await tenantRead(session, '/platform/audit/verification')), { headers: NO_STORE }),
  { roles: ['platform-operator'] },
);

export const GET = (request: Request) => get(request, undefined);
