import { randomUUID } from 'node:crypto';
import { withBff } from '@/lib/bff/handler';
import { ALERT_ROLES } from '@/lib/exec/alertsServer';
import { fhirFetch } from '@/lib/fhir/client';
import type { Role } from '@/lib/auth/session';

// Acknowledges one of the caller's alerts (R12, `$acknowledge`). It tells others the alert is being
// handled; it does not change the board. Another owner's alert is a 404 from the back end.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ALERT_ID = /^[A-Za-z0-9-]{1,64}$/;
const ROLES: Role[] = [...ALERT_ROLES];

type Context = { params: Promise<{ id: string }> };

const post = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!ALERT_ID.test(id)) return Response.json({ code: 'not-found' }, { status: 404, headers: NO_STORE });
    const { data } = await fhirFetch<{ id?: unknown; businessStatus?: { coding?: { code?: unknown }[] } }>(
      `/Task/${id}/$acknowledge`,
      { method: 'POST', token: session.backendToken, idempotencyKey: randomUUID() },
    );
    const status = data.businessStatus?.coding?.[0]?.code;
    return Response.json({ id, status: typeof status === 'string' ? status : 'acknowledged' }, { headers: NO_STORE });
  },
  { roles: ROLES },
);

export const POST = (request: Request, context: Context) => post(request, context);
