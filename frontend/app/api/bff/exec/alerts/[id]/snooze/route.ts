import { randomUUID } from 'node:crypto';
import { instantText } from '@/lib/exec/alerts';
import { withBff } from '@/lib/bff/handler';
import { ALERT_ROLES } from '@/lib/exec/alertsServer';
import { fhirFetch } from '@/lib/fhir/client';
import type { Role } from '@/lib/auth/session';

// Snoozes one of the caller's alerts for an hour (R12, `$snooze`): the next escalation moves one hour on.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ALERT_ID = /^[A-Za-z0-9-]{1,64}$/;
const ROLES: Role[] = [...ALERT_ROLES];

type Context = { params: Promise<{ id: string }> };
type Parameters = { parameter?: { name?: unknown; valueDateTime?: unknown }[] };

const post = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!ALERT_ID.test(id)) return Response.json({ code: 'not-found' }, { status: 404, headers: NO_STORE });
    const { data } = await fhirFetch<Parameters>(`/Task/${id}/$snooze`, {
      method: 'POST',
      token: session.backendToken,
      idempotencyKey: randomUUID(),
    });
    const due = data.parameter?.find((p) => p.name === 'escalationDueAt')?.valueDateTime;
    if (typeof due !== 'string') throw new Error('The back end sent no escalation time.');
    return Response.json({ alertId: id, escalatesAt: instantText(due) }, { headers: NO_STORE });
  },
  { roles: ROLES },
);

export const POST = (request: Request, context: Context) => post(request, context);
