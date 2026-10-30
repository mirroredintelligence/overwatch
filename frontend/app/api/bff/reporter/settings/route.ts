import { withBff } from '@/lib/bff/handler';
import { parseSettings } from '@/lib/reporter/answers';
import { reporterCall } from '@/lib/reporter/backend';

// GET /api/bff/reporter/settings (W37, W8E). The channel, the masked number and cover, the days until
// the next text code and the other phones signed in (DEC-819). Nothing in the answer is a whole number.
export const GET = withBff((_request, session) => reporterCall(session, '/reporter/settings', { parse: parseSettings }), {
  roles: ['reporter'],
});
