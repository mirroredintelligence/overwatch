import { readQueue } from '@/lib/clinical/clinicalServer';
import { withBff } from '@/lib/bff/handler';

// The clinical queue (W44). Only Waiting is listed: the back end lists requests still waiting. Mine and
// Done are answered 503 until the back end lists them.

const NO_STORE = { 'Cache-Control': 'no-store' };
const TABS = ['waiting', 'mine', 'done'] as const;

const get = withBff(
  async (request, session) => {
    const tab = new URL(request.url).searchParams.get('tab') ?? 'waiting';
    if (!(TABS as readonly string[]).includes(tab)) {
      return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    }
    if (tab !== 'waiting') {
      return Response.json({ code: 'unavailable', message: 'The service is unavailable. Try again shortly.' }, { status: 503, headers: NO_STORE });
    }
    return Response.json({ items: await readQueue(session) }, { headers: NO_STORE });
  },
  { roles: ['clinical'] },
);

export const GET = (request: Request) => get(request, undefined);
