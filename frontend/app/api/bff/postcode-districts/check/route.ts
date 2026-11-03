import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { invalidRequest } from '@/lib/lead/bffInput';
import { districtCheckFrom } from '@/lib/lead/postcodeDistricts';

// Step one of a service's postcode districts (DEC-1329): the district is checked and its postcode count is
// returned, so the lead can confirm or narrow it. Lead only. An answer that cannot be read is an error, never
// a count (fail closed).

const get = withBff(
  async (request, session) => {
    const text = new URL(request.url).searchParams.get('text');
    if (text === null || text.length === 0 || text.length > 16) throw invalidRequest();
    const { data } = await fhirFetch<unknown>(`/postcode-districts/check?text=${encodeURIComponent(text)}`, {
      token: session.backendToken,
      root: true,
    });
    const check = districtCheckFrom(data);
    if (check === null) throw invalidRequest();
    return Response.json(check, { headers: { 'Cache-Control': 'no-store' } });
  },
  { roles: ['lead'] },
);

export const GET = (request: Request) => get(request, undefined);
