import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { invalidRequest } from '@/lib/lead/bffInput';
import { flagItemsFrom } from '@/lib/lead/flags';

// The reports to check (W42). Lead only. "to-check" is the back end's open list (U39); "checked" is its closed
// list (W7B C). A list that cannot be read is an error, never an empty list (H-330).

const get = withBff(
  async (request, session) => {
    const state = new URL(request.url).searchParams.get('state') ?? 'to-check';
    if (state !== 'to-check' && state !== 'checked') throw invalidRequest();
    const status = state === 'checked' ? 'closed' : 'open';
    const { data } = await fhirFetch<unknown>(`/admin/report-flags?status=${status}`, { token: session.backendToken, root: true });
    const items = flagItemsFrom(data);
    const counts = state === 'checked' ? { toCheck: null, checked: items.length } : { toCheck: items.length, checked: null };
    return Response.json({ counts, items }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { roles: ['lead'] },
);

export const GET = (request: Request) => get(request, undefined);
