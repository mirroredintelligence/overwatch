import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';

// The clinical advisor's presence (W44): available, busy or away. Advisors see the count only; they see
// a name once a request is taken.

const NO_STORE = { 'Cache-Control': 'no-store' };
const PRESENCE = ['available', 'busy', 'away'] as const;

const put = withBff(
  async (request, session) => {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      body = undefined;
    }
    const presence = typeof body === 'object' && body !== null ? (body as { presence?: unknown }).presence : undefined;
    if (typeof presence !== 'string' || !(PRESENCE as readonly string[]).includes(presence)) {
      return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    }
    const { data } = await fhirFetch<{ presence?: unknown }>('/clinical/presence', {
      method: 'PUT',
      token: session.backendToken,
      body: { presence },
    });
    return Response.json({ presence: typeof data.presence === 'string' ? data.presence : presence }, { headers: NO_STORE });
  },
  { roles: ['clinical'] },
);

export const PUT = (request: Request) => put(request, undefined);
