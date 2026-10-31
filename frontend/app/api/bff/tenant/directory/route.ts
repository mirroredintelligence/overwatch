import { withBff } from '@/lib/bff/handler';
import { directoryBody } from '@/lib/tenantAdmin/bodies';
import { jsonBody, noContent, tenantWrite } from '@/lib/tenantAdmin/call';

// PUT /tenant/directory: binds the directory as pending; the platform operator verifies it.

const put = withBff(
  async (request, session) => {
    const body = directoryBody(await jsonBody(request));
    await tenantWrite(session, request, 'PUT', '/tenant/directory', body);
    return noContent();
  },
  { roles: ['tenant-admin'] },
);

export const PUT = (request: Request) => put(request, undefined);
