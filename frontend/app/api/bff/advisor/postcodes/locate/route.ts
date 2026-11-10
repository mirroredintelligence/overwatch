import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';

// The position of the postcode an advisor typed (DEC-1340), from OS Places through the back end. Only the typed
// postcode is sent; no patient field goes with it, and nothing is stored. Counts and positions only.

const NO_STORE = { 'Cache-Control': 'no-store' };
const UNAVAILABLE = { status: 'unavailable' };

const get = withBff(
  async (request, session) => {
    const postcode = new URL(request.url).searchParams.get('postcode') ?? '';
    if (postcode.length === 0 || postcode.length > 8) return Response.json(UNAVAILABLE, { headers: NO_STORE });
    try {
      const { data } = await fhirFetch<Record<string, unknown>>(
        `/clinical/postcodes/locate?postcode=${encodeURIComponent(postcode)}`,
        { token: session.backendToken, root: true },
      );
      return Response.json(data ?? UNAVAILABLE, { headers: NO_STORE });
    } catch {
      return Response.json(UNAVAILABLE, { headers: NO_STORE });
    }
  },
  { roles: ['advisor', 'clinical', 'lead', 'advisor-v2'] },
);

export const GET = (request: Request) => get(request, undefined);
