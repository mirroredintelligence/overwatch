import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { parseVersions } from '@/lib/tenantAdmin/views';

// GET /tenant/config/versions, newest first, with the diff of each against the version below it. Who wrote
// a draft or approved it is answered as "you or not" (the person's own subject is compared here), never as
// a reference to a person.

const get = withBff(
  async (_request, session) => Response.json(parseVersions(await tenantRead(session, '/tenant/config/versions'), session.sub), { headers: NO_STORE }),
  { roles: ['tenant-admin'] },
);

export const GET = (request: Request) => get(request, undefined);
