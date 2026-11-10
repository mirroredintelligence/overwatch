import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';

// The postcodes an advisor may pick from as they type (DEC-1332). The back end answers from its local postcode
// file only, so the typed text never goes to another service. Counts and postcodes only; no patient.

const NO_STORE = { 'Cache-Control': 'no-store' };
const PREFIX_MAX = 8;

const get = withBff(
  async (request, session) => {
    const prefix = new URL(request.url).searchParams.get('prefix') ?? '';
    if (prefix.length > PREFIX_MAX) return Response.json({ postcodes: [] }, { headers: NO_STORE });
    const { data } = await fhirFetch<{ postcodes?: unknown }>(
      `/clinical/postcodes?prefix=${encodeURIComponent(prefix)}`,
      { token: session.backendToken, root: true },
    );
    const postcodes = Array.isArray(data?.postcodes)
      ? data.postcodes.filter((item): item is string => typeof item === 'string')
      : [];
    return Response.json({ postcodes }, { headers: NO_STORE });
  },
  { roles: ['advisor', 'clinical', 'lead', 'advisor-v2'] },
);

export const GET = (request: Request) => get(request, undefined);
