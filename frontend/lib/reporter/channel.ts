import { bffRequest } from './browser';

// Recording how the reporter wants to be contacted, from the browser (W33, W34, W37, W8E). Before sign-in it
// is recorded for the phone's device, which a text code verified in the last ten minutes (the BFF's
// identity/channel route); behind a session it is the settings change (reporter/channel). The two never
// mix: a page that can be reached either way tries the session first and falls back to the device.

export type ChannelWord = 'app' | 'text' | 'email';
export type ChannelResult = 'ok' | 'needs-code' | 'failed';

const saved = (reply: { status: number; body: unknown }) => reply.status === 200 && (reply.body as { ok?: unknown } | undefined)?.ok === true;

/** For a phone with no session yet. `needs-code` is a device whose code has timed out. */
export async function recordChannelForDevice(channel: ChannelWord): Promise<ChannelResult> {
  const reply = await bffRequest('/api/bff/identity/channel', { method: 'POST', body: { channel } });
  if (saved(reply)) return 'ok';
  return reply.status === 403 ? 'needs-code' : 'failed';
}

/** For a signed-in reporter. A 401 is "no session" (the caller may fall back to the device). */
export async function recordChannelForSession(channel: ChannelWord): Promise<ChannelResult | 'no-session'> {
  const reply = await bffRequest('/api/bff/reporter/channel', { method: 'POST', body: { channel } });
  if (saved(reply)) return 'ok';
  return reply.status === 401 ? 'no-session' : 'failed';
}

/** A page reached with or without a session: the session's route, then the device's when there is none. */
export async function recordChannel(channel: ChannelWord): Promise<ChannelResult> {
  const withSession = await recordChannelForSession(channel);
  return withSession === 'no-session' ? recordChannelForDevice(channel) : withSession;
}
