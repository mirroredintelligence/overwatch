import { withBff } from '@/lib/bff/handler';
import type { Role } from '@/lib/auth/session';

// The state of an advisor's request for advice (W45): waiting, taken, advised or returned. The back end
// has no read an advisor can make of one request yet (the queue is the clinician's, and it lists only
// waiting requests), so this answers 503 and the dialog keeps saying it is waiting. Nothing is guessed.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = ['advisor', 'lead'];

const get = withBff(
  async () => Response.json({ code: 'unavailable', message: 'The service is unavailable. Try again shortly.' }, { status: 503, headers: NO_STORE }),
  { roles: ROLES },
);

export const GET = (request: Request) => get(request, undefined);
