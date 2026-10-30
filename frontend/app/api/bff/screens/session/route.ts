import { hostOf } from '@/lib/links/server';
import { json, notFound, refuse, screenFailure } from '@/lib/screens/answers';
import { deviceFrom, forgetDevice } from '@/lib/screens/cookies';
import { isSameOriginRequest } from '@/lib/screens/origin';
import { exchangeDeviceToken, ScreenApiError } from '@/lib/screens/server';
import { createWallSession } from '@/lib/screens/wall';

// A paired screen's wall token lasts an hour (TEN-043), so a screen that has just opened, or whose
// session has ended, asks here for a new one with the device token only this route reads. A screen
// the back end no longer knows (revoked) is told so and forgets its device token. No tenant is read
// from the request: the host it was opened on names it.

export async function POST(request: Request): Promise<Response> {
  if (!isSameOriginRequest(request)) return refuse(403, 'forbidden', 'You cannot do that.');
  try {
    const device = await deviceFrom(request);
    if (device === null) return notFound();
    try {
      await createWallSession(await exchangeDeviceToken(hostOf(request), device));
    } catch (error) {
      if (error instanceof ScreenApiError && error.kind === 'not-found') await forgetDevice();
      throw error;
    }
    return json(200, { status: 'paired' });
  } catch (error) {
    return screenFailure(error);
  }
}
