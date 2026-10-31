import { withBff } from '@/lib/bff/handler';
import { channelBody } from '@/lib/tenantAdmin/bodies';
import { jsonBody, NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { parseId } from '@/lib/tenantAdmin/views';

// POST /tenant/channels: an email channel. The text channel is the platform operator's, and the reference of a
// channel's secret is never sent through a browser (lib/tenantAdmin/bodies.ts).

const post = withBff(
  async (request, session) => {
    const body = channelBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', '/tenant/channels', body);
    return Response.json(parseId(data), { status: 201, headers: NO_STORE });
  },
  { roles: ['tenant-admin'] },
);

export const POST = (request: Request) => post(request, undefined);
