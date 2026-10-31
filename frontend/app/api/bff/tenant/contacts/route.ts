import { withBff } from '@/lib/bff/handler';
import { contactBody } from '@/lib/tenantAdmin/bodies';
import { jsonBody, noContent, tenantWrite } from '@/lib/tenantAdmin/call';

// PUT /tenant/contacts: one contact of a kind (one per kind).

const put = withBff(
  async (request, session) => {
    const body = contactBody(await jsonBody(request));
    await tenantWrite(session, request, 'PUT', '/tenant/contacts', body);
    return noContent();
  },
  { roles: ['tenant-admin'] },
);

export const PUT = (request: Request) => put(request, undefined);
