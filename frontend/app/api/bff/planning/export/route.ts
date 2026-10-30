import { withBff } from '@/lib/bff/handler';
import { NO_STORE } from '@/lib/console/backend';
import { toCsv } from '@/lib/planning/csv';
import { isNeed, isPeriod, PLANNING_ROLES, planningCall } from '@/lib/planning/backend';

// The planning table as CSV (W51). It is written from the same answer the page shows, so it holds
// no more than the page does: a count under 10 is an empty field.

const get = withBff(
  async (request, session) => {
    const params = new URL(request.url).searchParams;
    const period = params.get('period') ?? '90d';
    const need = params.get('need') ?? 'all';
    if (!isPeriod(period) || !isNeed(need)) {
      return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    }
    const { data } = await planningCall(session, period, need);
    return new Response(toCsv(data), {
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': `attachment; filename="planning-${period}-${need}.csv"`,
        'Cache-Control': 'no-store',
      },
    });
  },
  { roles: [...PLANNING_ROLES] },
);

export const GET = (request: Request) => get(request, undefined);
