import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseVersion } from '@/lib/tenantAdmin/views';

// GET /tenant/config/versions/{n}: one version with its diff.

type Context = { params: Promise<Record<string, string>> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const n = await segment(context, 'n', 'version');
    return Response.json(parseVersion(await tenantRead(session, `/tenant/config/versions/${n}`), session.sub), { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
