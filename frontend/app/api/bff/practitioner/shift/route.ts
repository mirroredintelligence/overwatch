import { withBff } from '@/lib/bff/handler';
import { parseShift } from '@/lib/practitioner/answers';
import { reporterCall } from '@/lib/reporter/backend';

// GET /api/bff/practitioner/shift (DEC-1306 to DEC-1309). The practitioner's shift home as the back end
// reads it from the graph: the optional status, the location choice, today's visits, the next one, the
// offers waiting and the round. Only the area sector, the need in words and times: no address, contact or
// postcode comes on this route. The practitioner signs in as a reporter does (the device sign-in).
export const GET = withBff(
  async (_request, session) => reporterCall(session, '/practitioner/shift', { parse: parseShift }),
  { roles: ['reporter'] },
);
