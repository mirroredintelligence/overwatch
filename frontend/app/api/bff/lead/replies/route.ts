import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { failedRepliesFrom } from '@/lib/lead/failedReplies';

// The text replies the system could not take in and that still wait for the shift lead (DEC-1359). Lead only. A
// list that cannot be read is an error, never an empty list (H-330).

const get = withBff(
  async (_request, session) => {
    const { data } = await fhirFetch<unknown>('/admin/failed-replies', { root: true, token: session.backendToken, cache: 'no-store' });
    return Response.json({ items: failedRepliesFrom(data) }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { roles: ['lead'] },
);

export const GET = (request: Request) => get(request, undefined);
