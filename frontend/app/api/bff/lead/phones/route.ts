import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { phonesFrom } from '@/lib/lead/phones';

// The phones and the services each holds now (W43). Lead only. Each phone is its last digits only; a phone is
// never shown in full, by this route or any other (H-331). A malformed answer is an error, never an empty list.

const get = withBff(
  async (_request, session) => {
    const { data } = await fhirFetch<unknown>('/lead/phones', { root: true, token: session.backendToken, cache: 'no-store' });
    return Response.json({ phones: phonesFrom(data) }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { roles: ['lead'] },
);

export const GET = (request: Request) => get(request, undefined);
