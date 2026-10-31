import { withBff } from '@/lib/bff/handler';
import { mappingBody } from '@/lib/tenantAdmin/bodies';
import { jsonBody, noContent, tenantWrite } from '@/lib/tenantAdmin/call';

// PUT /tenant/role-mappings: maps a directory group to a staff role (never to the administrator's own).

const put = withBff(
  async (request, session) => {
    const body = mappingBody(await jsonBody(request));
    await tenantWrite(session, request, 'PUT', '/tenant/role-mappings', body);
    return noContent();
  },
  { roles: ['tenant-admin'] },
);

export const PUT = (request: Request) => put(request, undefined);
