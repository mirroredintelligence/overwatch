import { withBff } from '@/lib/bff/handler';
import { CONSOLE_ROLES, consoleCall, NO_STORE } from '@/lib/console/backend';
import { DEVICES, RANGES, TABS } from '@/lib/console/insight';

// One tab of the insight page (W49, W9F). The tab, the range and the device are checked against their
// lists; any other query parameter is dropped, so nothing the browser sends reaches the back end but
// these. The release comparison has no device, so none is forwarded for it.

type Context = { params: Promise<{ tab: string }> };

const get = withBff<Context>(
  async (request, session, context) => {
    const { tab } = await context.params;
    const params = new URL(request.url).searchParams;
    const range = params.get('range') ?? '7d';
    const device = params.get('device');
    const knownTab = (TABS as readonly string[]).includes(tab);
    const knownRange = RANGES.some((item) => item.value === range);
    const knownDevice = device === null || DEVICES.some((item) => item.value === device);
    if (!knownTab || !knownRange || !knownDevice) {
      return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
    }
    const query = `range=${range}${device === null || tab === 'releases' ? '' : `&device=${device}`}`;
    const { data } = await consoleCall(session, `/support/insight/${tab}?${query}`);
    return Response.json(data, { headers: NO_STORE });
  },
  { roles: [...CONSOLE_ROLES] },
);

export const GET = (request: Request, context: Context) => get(request, context);
