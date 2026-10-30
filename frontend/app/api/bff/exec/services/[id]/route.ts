import { readBoard } from '@/lib/board/read';
import { withBff } from '@/lib/bff/handler';
import { ALERT_ROLES } from '@/lib/exec/alertsServer';
import type { Role } from '@/lib/auth/session';

// One service from the board the caller can read (W40). The back end has no single-service read for
// executives, so the board's entry is the answer; a service not on the board is a 404.

const NO_STORE = { 'Cache-Control': 'no-store' };
const SERVICE_ID = /^[A-Za-z0-9-]{1,64}$/;
const ROLES: Role[] = [...ALERT_ROLES];

type Context = { params: Promise<{ id: string }> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!SERVICE_ID.test(id)) return Response.json({ code: 'not-found' }, { status: 404, headers: NO_STORE });
    const board = await readBoard(session);
    const entry = board.entries.find((item) => item.serviceId === id);
    if (!entry) return Response.json({ code: 'not-found' }, { status: 404, headers: NO_STORE });
    return Response.json(entry, { headers: NO_STORE });
  },
  { roles: ROLES },
);

export const GET = (request: Request, context: Context) => get(request, context);
