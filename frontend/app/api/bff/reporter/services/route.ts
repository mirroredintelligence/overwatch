import { withBff } from '@/lib/bff/handler';
import { parseServices } from '@/lib/reporter/answers';
import { reporterCall } from '@/lib/reporter/backend';

// GET /api/bff/reporter/services (W38, W8E). The reporter's services with their states, from the
// back end's `GET /reporter/services`: the back end reads them from the graph at the time of the
// request, so a cover that began after sign-in is listed at once (DEC-814, DEC-815).
export const GET = withBff((_request, session) => reporterCall(session, '/reporter/services', { parse: parseServices }), {
  roles: ['reporter'],
});
