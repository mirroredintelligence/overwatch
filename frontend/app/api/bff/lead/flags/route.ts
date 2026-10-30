import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { invalidRequest } from '@/lib/lead/bffInput';
import { flagItemsFrom } from '@/lib/lead/flags';
import { notBuilt } from '@/lib/lead/notBuilt';

// The reports to check (W42). Lead only. "to-check" is the back end's open list (U39); "checked" is not
// listed by the back end yet, so it answers 501 rather than an empty list (H-330).

const get = withBff(
  async (request, session) => {
    const state = new URL(request.url).searchParams.get('state') ?? 'to-check';
    if (state === 'checked') return notBuilt();
    if (state !== 'to-check') throw invalidRequest();
    const { data } = await fhirFetch<unknown>('/admin/report-flags?status=open', { token: session.backendToken, root: true });
    const items = flagItemsFrom(data);
    return Response.json(
      { counts: { toCheck: items.length, checked: null }, items },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { roles: ['lead'] },
);

export const GET = (request: Request) => get(request, undefined);
