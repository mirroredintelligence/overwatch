import { withBff } from '@/lib/bff/handler';
import { CONSOLE_ROLES, consoleCall, NO_STORE } from '@/lib/console/backend';
import { RANGES, TABS } from '@/lib/console/insight';

// One tab of the insight page (W49). The tab and the range are checked against their lists; any
// other query parameter is dropped, so nothing the browser sends reaches the back end but these.

type Context = { params: Promise<{ tab: string }> };

const get = withBff<Context>(
  async (request, session, context) => {
    const { tab } = await context.params;
    const range = new URL(request.url).searchParams.get('range') ?? '7d';
    const knownTab = (TABS as readonly string[]).includes(tab);
    const knownRange = RANGES.some((item) => item.value === range);
    if (!knownTab || !knownRange) {
      return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    }
    const { data } = await consoleCall(session, `/support/insight/${tab}?range=${range}`);
    return Response.json(data, { headers: NO_STORE });
  },
  { roles: [...CONSOLE_ROLES] },
);

export const GET = (request: Request, context: Context) => get(request, context);
