import { withBff } from '@/lib/bff/handler';
import { isNeed, isPeriod, PLANNING_ROLES, planningCall } from '@/lib/planning/backend';
import { NO_STORE } from '@/lib/console/backend';

// The planning view's data (W51). The period and the need are checked against their lists; the
// browser never names an organisation.

const get = withBff(
  async (request, session) => {
    const params = new URL(request.url).searchParams;
    const period = params.get('period') ?? '90d';
    const need = params.get('need') ?? 'all';
    if (!isPeriod(period) || !isNeed(need)) {
      return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    }
    const { data } = await planningCall(session, period, need);
    return Response.json(data, { headers: NO_STORE });
  },
  { roles: [...PLANNING_ROLES] },
);

export const GET = (request: Request) => get(request, undefined);
