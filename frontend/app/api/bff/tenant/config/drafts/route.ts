import { withBff } from '@/lib/bff/handler';
import { draftBody } from '@/lib/tenantAdmin/bodies';
import { jsonBody, NO_STORE, tenantWrite } from '@/lib/tenantAdmin/call';
import { parseDraftResult } from '@/lib/tenantAdmin/views';

// POST /tenant/config/drafts: a change to the settings, from the version in force the page read. A stale
// `basedOn` is the back end's 409; a clinical change needs two approvers who are not its author.

const post = withBff(
  async (request, session) => {
    const body = draftBody(await jsonBody(request));
    const data = await tenantWrite(session, request, 'POST', '/tenant/config/drafts', body);
    return Response.json(parseDraftResult(data), { status: 201, headers: NO_STORE });
  },
  { roles: ['tenant-admin'] },
);

export const POST = (request: Request) => post(request, undefined);
