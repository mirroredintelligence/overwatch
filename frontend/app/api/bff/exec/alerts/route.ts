import { ALERT_ROLES, openAlerts } from '@/lib/exec/alertsServer';
import { withBff } from '@/lib/bff/handler';
import type { Role } from '@/lib/auth/session';

// The executive's open alerts (W40). The back end lists only open alerts (R12), so the acknowledged and
// closed tabs are answered 503 here, and the screen says so. Nothing in the request names a tenant or a
// practitioner: the alerts are the token's owner's.

const NO_STORE = { 'Cache-Control': 'no-store' };
const STATES = ['open', 'acknowledged', 'closed'] as const;
const ROLES: Role[] = [...ALERT_ROLES];

const get = withBff(
  async (request, session) => {
    const state = new URL(request.url).searchParams.get('state') ?? 'open';
    if (!(STATES as readonly string[]).includes(state)) {
      return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    }
    if (state !== 'open') {
      return Response.json({ code: 'unavailable', message: 'The service is unavailable. Try again shortly.' }, { status: 503, headers: NO_STORE });
    }
    const items = await openAlerts(session);
    return Response.json({ counts: { open: items.length }, items }, { headers: NO_STORE });
  },
  { roles: ROLES },
);

export const GET = (request: Request) => get(request, undefined);
