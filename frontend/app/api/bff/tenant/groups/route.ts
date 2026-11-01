import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { parseGroups } from '@/lib/tenantAdmin/views';

// GET /tenant/groups: the groups Overwatch made in the organisation's directory and who is in each, read from the
// directory now (DEC-1317). Nothing about a member is stored by Overwatch.

const get = withBff(
  async (_request, session) => Response.json(parseGroups(await tenantRead(session, '/tenant/groups')), { headers: NO_STORE }),
  { roles: ['tenant-admin'] },
);

export const GET = (request: Request) => get(request, undefined);
