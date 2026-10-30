import { ALERT_ROLES, ALERT_STATES, alertsByState, openAlerts, type AlertState } from '@/lib/exec/alertsServer';
import { withBff } from '@/lib/bff/handler';
import type { Role } from '@/lib/auth/session';

// The executive's alerts (W40): open, acknowledged or closed, each the back end's own list for the token's
// owner (R12, W7A DEC-775: the latest first, at most 50). Nothing in the request names a tenant or a
// practitioner. `counts.open` is the number open now, whichever tab is asked for.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = [...ALERT_ROLES];

const get = withBff(
  async (request, session) => {
    const state = new URL(request.url).searchParams.get('state') ?? 'open';
    if (!(ALERT_STATES as readonly string[]).includes(state)) {
      return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    }
    if (state !== 'open') {
      const [items, open] = await Promise.all([alertsByState(session, state as AlertState), openAlerts(session)]);
      return Response.json({ counts: { open: open.length }, items }, { headers: NO_STORE });
    }
    const items = await openAlerts(session);
    return Response.json({ counts: { open: items.length }, items }, { headers: NO_STORE });
  },
  { roles: ROLES },
);

export const GET = (request: Request) => get(request, undefined);
