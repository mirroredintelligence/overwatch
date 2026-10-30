import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { invalidRequest } from '@/lib/lead/bffInput';
import { postsFrom, publicPost } from '@/lib/lead/reporters';

// The reporter posts for the lead's change-number page (W18): each post's service, role, channel, the last four
// digits of its number and any cover end. Lead only. With ?service= only that service's posts. The role id is
// never returned to the browser (DEC-803).

const SERVICE_ID = /^[A-Za-z0-9.-]{1,64}$/;

const get = withBff(
  async (request, session) => {
    const service = new URL(request.url).searchParams.get('service');
    if (service !== null && !SERVICE_ID.test(service)) throw invalidRequest();
    const path = service === null ? '/lead/reporters' : `/lead/reporters?service=${encodeURIComponent(service)}`;
    const { data } = await fhirFetch<unknown>(path, { root: true, token: session.backendToken, cache: 'no-store' });
    return Response.json(
      { reporters: postsFrom(data).map(publicPost) },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { roles: ['lead'] },
);

export const GET = (request: Request) => get(request, undefined);
