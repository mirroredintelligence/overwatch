import { readList, TABS, type Tab } from '@/lib/clinical/clinicalServer';
import { withBff } from '@/lib/bff/handler';

// The clinical lists (W44, R13, DEC-774): Waiting, Mine and Done, each the back end's own list for the
// signed-in clinician. Each request carries the case's glance and never a postcode or a person's id.

const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff(
  async (request, session) => {
    const tab = new URL(request.url).searchParams.get('tab') ?? 'waiting';
    if (!(TABS as string[]).includes(tab)) {
      return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    }
    return Response.json({ items: await readList(session, tab as Tab) }, { headers: NO_STORE });
  },
  { roles: ['clinical'] },
);

export const GET = (request: Request) => get(request, undefined);
