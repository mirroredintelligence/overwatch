import { withBff } from '@/lib/bff/handler';
import { parseCover } from '@/lib/reporter/answers';
import { plain, readJson, reporterCall } from '@/lib/reporter/backend';
import { coverBody } from '@/lib/reporter/cover';

// POST /api/bff/reporter/cover (W37, W8E). Hands every post the reporter owns to a cover number, for
// tonight, this week or a date (DEC-820). The back end finds or makes the cover practitioner, keeps the
// number as the post's cover contact and audits only its hash; the answer says when the cover ends and
// how many services moved, never the number.
export const POST = withBff(
  async (request, session) => {
    const body = coverBody(await readJson(request));
    if (body === null) return plain(400, 'invalid');
    return reporterCall(session, '/reporter/cover', { body, parse: parseCover });
  },
  { roles: ['reporter'] },
);
