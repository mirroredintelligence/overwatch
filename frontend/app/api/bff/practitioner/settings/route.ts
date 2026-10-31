import { withBff } from '@/lib/bff/handler';
import { LOCATIONS, parseSettings, SHIFT_STATUSES } from '@/lib/practitioner/answers';
import { onlyFields, plain, readJson, reporterCall } from '@/lib/reporter/backend';

// PUT /api/bff/practitioner/settings (DEC-1306 to DEC-1309). The optional shift status (a word, or null to
// clear it) and the location choice (`travel`: an estimated arrival while travelling to a visit; `never`).
// Either may be left out. Nothing else goes through: a position, a person or a tenant in the body is a 400.
export const PUT = withBff(
  async (request, session) => {
    const body = await readJson(request);
    if (!onlyFields(body, ['status', 'location'])) return plain(400, 'invalid');
    const { status, location } = body;
    const sent: Record<string, unknown> = {};
    if ('status' in body) {
      if (status !== null && !(typeof status === 'string' && (SHIFT_STATUSES as readonly string[]).includes(status))) return plain(400, 'invalid');
      sent.status = status;
    }
    if ('location' in body) {
      if (!(typeof location === 'string' && (LOCATIONS as readonly string[]).includes(location))) return plain(400, 'invalid');
      sent.location = location;
    }
    if (Object.keys(sent).length === 0) return plain(400, 'invalid');
    return reporterCall(session, '/practitioner/settings', { method: 'PUT', body: sent, parse: parseSettings });
  },
  { roles: ['reporter'] },
);
