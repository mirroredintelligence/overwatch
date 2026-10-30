import { withBff } from '@/lib/bff/handler';
import { CHANNELS, parseChannel } from '@/lib/reporter/answers';
import { json, onlyFields, plain, readJson, reporterCall } from '@/lib/reporter/backend';

// POST /api/bff/reporter/channel (W37, W8E). How the reporter is contacted, behind a session: the
// settings change and "use text" from the notifications-off page. (Before sign-in, set-up and the locked
// PIN use /api/bff/identity/channel, which the phone proves with a text code instead.) `email` needs an
// address on record for every post: the back end says so with a 400.
export const POST = withBff(
  async (request, session) => {
    const body = await readJson(request);
    if (!onlyFields(body, ['channel']) || !(CHANNELS as readonly string[]).includes(body.channel as string)) return plain(400, 'invalid');
    const reply = await reporterCall(session, '/reporter/channel', { body: { channel: body.channel }, parse: parseChannel });
    if (!reply.ok) return reply;
    return json({ ok: true, ...((await reply.json()) as object) });
  },
  { roles: ['reporter'] },
);
