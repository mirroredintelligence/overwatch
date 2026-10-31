import { withBff } from '@/lib/bff/handler';
import { retentionBody } from '@/lib/tenantAdmin/bodies';
import { jsonBody, NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { parseStored } from '@/lib/tenantAdmin/views';

// PUT /tenant/retention: the defaults, or one rule per data class.

const put = withBff(
  async (request, session) => {
    const body = retentionBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'PUT', '/tenant/retention', body);
    return Response.json(parseStored(data), { headers: NO_STORE });
  },
  { roles: ['tenant-admin'] },
);

export const PUT = (request: Request) => put(request, undefined);
