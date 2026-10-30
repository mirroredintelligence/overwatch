import { withBff } from '@/lib/bff/handler';
import { parseSummary } from '@/lib/reporter/answers';
import { reporterCall } from '@/lib/reporter/backend';

// GET /api/bff/reporter/setup-summary (W34, W8E). The All-set page: the service, how the reporter is
// contacted, the masked number, the next update due and the days until the text code (DEC-826).
export const GET = withBff((_request, session) => reporterCall(session, '/reporter/setup-summary', { parse: parseSummary }), {
  roles: ['reporter'],
});
