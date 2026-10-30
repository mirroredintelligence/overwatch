import { CHANNELS, parseChannel } from '@/lib/reporter/answers';
import { json, onlyFields, plain, readJson } from '@/lib/reporter/backend';
import { preSession } from '@/lib/reporter/bff';
import { ensureDevice } from '@/lib/reporter/device';
import { identityOrUnavailable, throttled } from '@/lib/reporter/identity';

// POST /api/bff/identity/channel (W33, W34, W37, W7C DEC-813, W8E). How the reporter wants to be
// contacted, recorded before anyone is signed in: the set-up channel step, the "use text" of the home
// screen and notifications steps, and the locked PIN's "use text". The phone proves itself by a text
// code in the last ten minutes; the back end answers 403 for a device it cannot use, shown here as "get
// a code first". Behind a session the same change is /api/bff/reporter/channel.
export const POST = preSession(async (request) => {
  const body = await readJson(request);
  if (!onlyFields(body, ['channel']) || !(CHANNELS as readonly string[]).includes(body.channel as string)) return plain(400, 'invalid');
  const deviceId = await ensureDevice(request);
  const reply = await identityOrUnavailable(request, { method: 'POST', path: '/identity/channel', body: { deviceId, channel: body.channel } });
  if (reply instanceof Response) return reply;
  if (reply.status === 403) return plain(403, 'needs-code');
  if (reply.status === 429) return throttled(reply);
  const parsed = reply.status === 200 ? parseChannel(reply.body) : null;
  return parsed === null ? plain(503, 'unavailable') : json({ ok: true, ...parsed });
});
