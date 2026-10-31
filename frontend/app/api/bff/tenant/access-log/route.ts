import { withBff } from '@/lib/bff/handler';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { parseLog } from '@/lib/tenantAdmin/views';

// GET /tenant/access-log: what the platform's own people did in this tenant, newest first. The window is
// the days the page asks for (1 to 400), or 90.

const DEFAULT_DAYS = 90;

function daysOf(request: Request): number {
  const raw = new URL(request.url).searchParams.get('days');
  if (raw === null || !/^[0-9]{1,4}$/.test(raw)) return DEFAULT_DAYS;
  const days = Number(raw);
  return days >= 1 && days <= 400 ? days : DEFAULT_DAYS;
}

const get = withBff(
  async (request, session) => Response.json(parseLog(await tenantRead(session, `/tenant/access-log?days=${daysOf(request)}`)), { headers: NO_STORE }),
  { roles: ['tenant-admin'] },
);

export const GET = (request: Request) => get(request, undefined);
