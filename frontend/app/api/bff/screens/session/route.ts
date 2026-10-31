import { hostOf } from '@/lib/links/server';
import { destroySession } from '@/lib/auth/session';
import { json, notFound, refuse, screenFailure } from '@/lib/screens/answers';
import { deviceFrom, forgetDevice } from '@/lib/screens/cookies';
import { isSameOriginRequest } from '@/lib/screens/origin';
import { exchangeDeviceToken, ScreenApiError } from '@/lib/screens/server';
import { createWallSession } from '@/lib/screens/wall';

// A paired screen's wall token lasts an hour (TEN-043), so a screen that has just opened, or whose
// session has ended, asks here for a new one with the device token only this route reads. A screen
// the back end no longer knows (a lead disconnected it) is told so, forgets its device token and ends the
// wall session it still held (W9I), so the pairing page does not send it back to a board it cannot read. No tenant is read
// from the request: the host it was opened on names it.

const DISCONNECTED = 'This screen was disconnected.';

export async function POST(request: Request): Promise<Response> {
  if (!isSameOriginRequest(request)) return refuse(403, 'forbidden', 'You cannot do that.');
  try {
    const device = await deviceFrom(request);
    if (device === null) return notFound();
    try {
      const host = hostOf(request);
      await createWallSession(await exchangeDeviceToken(host, device), host);
    } catch (error) {
      if (error instanceof ScreenApiError && error.kind === 'not-found') {
        await forgetDevice();
        await destroySession();
        return json(404, { code: 'disconnected', message: DISCONNECTED });
      }
      throw error;
    }
    return json(200, { status: 'paired' });
  } catch (error) {
    return screenFailure(error);
  }
}
