import { withBff } from '@/lib/bff/handler';
import { channelBody } from '@/lib/tenantAdmin/bodies';
import { jsonBody, NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { segment } from '@/lib/tenantAdmin/ids';
import { parseId } from '@/lib/tenantAdmin/views';

// PUT /tenant/channels/{id}: changes an email channel (its sender, or retires it).

type Context = { params: Promise<Record<string, string>> };

const put = withBff<Context>(
  async (request, session, context) => {
    const id = await segment(context, 'id', 'channel');
    const body = channelBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'PUT', `/tenant/channels/${id}`, body);
    return Response.json(parseId(data), { headers: NO_STORE });
  },
  { roles: ['tenant-admin'], idScoped: true },
);

export const PUT = (request: Request, context: Context) => put(request, context);
