import { withBff } from '@/lib/bff/handler';
import { ALERT_ROLES } from '@/lib/exec/alertsServer';
import { readWeekSummary } from '@/lib/exec/weekServer';
import { weekEndingDefault, weekStartFor } from '@/lib/exec/weekSummary';
import type { Role } from '@/lib/auth/session';

// The week summary for the caller (W41). `ending` is the Sunday that closes the week; the default is the
// last complete week. Nothing here names a tenant or an organisation.

const NO_STORE = { 'Cache-Control': 'no-store' };
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const ROLES: Role[] = [...ALERT_ROLES];

const get = withBff(
  async (request, session) => {
    const ending = new URL(request.url).searchParams.get('ending') ?? weekEndingDefault(new Date());
    let refused = !DAY.test(ending);
    if (!refused) {
      try {
        weekStartFor(ending);
      } catch {
        refused = true;
      }
    }
    if (refused) return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    return Response.json(await readWeekSummary(session, ending), { headers: NO_STORE });
  },
  { roles: ROLES },
);

export const GET = (request: Request) => get(request, undefined);
