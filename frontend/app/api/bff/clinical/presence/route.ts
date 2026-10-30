import { PRESENCES, readPresence } from '@/lib/clinical/clinicalServer';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';

// The clinical advisor's presence (W44): available, busy or away. The read gives the clinician's own
// presence (null when none is set or it has lapsed) and the count of advisors available; advisors see
// the count only, and a name only once a request is taken. Both calls are at the back end's root.

const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff(
  async (_request, session) => Response.json(await readPresence(session), { headers: NO_STORE }),
  { roles: ['clinical'] },
);

const put = withBff(
  async (request, session) => {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      body = undefined;
    }
    const presence = typeof body === 'object' && body !== null ? (body as { presence?: unknown }).presence : undefined;
    if (typeof presence !== 'string' || !(PRESENCES as readonly string[]).includes(presence)) {
      return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    }
    const { data } = await fhirFetch<{ presence?: unknown }>('/clinical/presence', {
      method: 'PUT',
      token: session.backendToken,
      body: { presence },
      root: true,
    });
    return Response.json({ presence: typeof data.presence === 'string' ? data.presence : presence }, { headers: NO_STORE });
  },
  { roles: ['clinical'] },
);

export const GET = (request: Request) => get(request, undefined);
export const PUT = (request: Request) => put(request, undefined);
