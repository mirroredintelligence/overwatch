import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { invalidRequest } from '@/lib/lead/bffInput';

// Step two of a service's postcode districts (DEC-1329): the lead confirms a district and it is queued for a
// background download. Nothing downloads in this request. Lead only; the BFF checks the CSRF token on a POST.

const post = withBff(
  async (request, session) => {
    const text = new URL(request.url).searchParams.get('text');
    if (text === null || text.length === 0 || text.length > 16) throw invalidRequest();
    const { data } = await fhirFetch<unknown>(`/postcode-districts/download?text=${encodeURIComponent(text)}`, {
      method: 'POST',
      body: {},
      token: session.backendToken,
      root: true,
    });
    return Response.json(data, { status: 202, headers: { 'Cache-Control': 'no-store' } });
  },
  { roles: ['lead'] },
);

export const POST = (request: Request) => post(request, undefined);
