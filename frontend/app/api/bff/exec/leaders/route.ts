import { withBff } from '@/lib/bff/handler';
import { ALERT_ROLES } from '@/lib/exec/alertsServer';
import { leadersFromBundle } from '@/lib/exec/leaders';
import { fhirFetch } from '@/lib/fhir/client';
import type { Role } from '@/lib/auth/session';

// The leaders a deputy can be chosen from (W39, W7A DEC-776): the back end's leadership read, an id and a
// display name for each, never the caller. No phone, email or role is sent or kept.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = [...ALERT_ROLES];

const get = withBff(
  async (_request, session) => {
    const { data } = await fhirFetch<unknown>('/Practitioner?role=leadership', { token: session.backendToken });
    return Response.json({ leaders: leadersFromBundle(data) }, { headers: NO_STORE });
  },
  { roles: ROLES },
);

export const GET = (request: Request) => get(request, undefined);
