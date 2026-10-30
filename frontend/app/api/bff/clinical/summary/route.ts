import { readAvailable, readQueue } from '@/lib/clinical/clinicalServer';
import { withBff } from '@/lib/bff/handler';

// The counts a clinical advisor and the advisors see (W44, W45): how many requests wait, and how many
// advisors are available. Counts only: no name, no case.

const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff(
  async (_request, session) => {
    const available = await readAvailable(session);
    if (session.role !== 'clinical') return Response.json({ available }, { headers: NO_STORE });
    const waiting = (await readQueue(session)).length;
    return Response.json({ waiting, available }, { headers: NO_STORE });
  },
  { roles: ['advisor', 'clinical', 'lead'] },
);

export const GET = (request: Request) => get(request, undefined);
