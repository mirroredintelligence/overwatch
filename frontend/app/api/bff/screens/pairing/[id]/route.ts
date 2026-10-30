import { hostOf } from '@/lib/links/server';
import { json, notFound, screenFailure } from '@/lib/screens/answers';
import { deviceFrom, forgetDevice, forgetPairing, pairingFrom, rememberDevice } from '@/lib/screens/cookies';
import { claimPairing, exchangeDeviceToken, ScreenApiError } from '@/lib/screens/server';
import { createWallSession } from '@/lib/screens/wall';

// The display asks whether a lead has connected it. When the back end says so it hands over the
// device token once. The BFF keeps it in a sealed cookie FIRST (a failed trade must not lose the one
// chance to collect it), trades it for the one-hour wall token and makes the wall session. The page
// is told `paired` and nothing else: neither token ever reaches browser JavaScript.

type Context = { params: Promise<{ id: string }> };

async function startSession(host: string | null, deviceToken: string): Promise<Response> {
  try {
    await createWallSession(await exchangeDeviceToken(host, deviceToken));
    return json(200, { status: 'paired' });
  } catch (error) {
    if (!(error instanceof ScreenApiError)) throw error;
    if (error.kind === 'not-found') {
      // The back end does not know this screen (revoked in the moment since): start again.
      await forgetDevice();
      return json(200, { status: 'expired' });
    }
    // The back end could not be asked or answered oddly. The device token is kept: the page asks to
    // renew the session, which trades it again.
    return json(200, { status: 'connecting' });
  }
}

export async function GET(request: Request, context: Context): Promise<Response> {
  const { id } = await context.params;
  try {
    const held = await pairingFrom(request);
    if (held === null || held.pairingId !== id) return notFound();
    const host = hostOf(request);

    let claim;
    try {
      claim = await claimPairing(host, id, held.screenSecret);
    } catch (error) {
      if (error instanceof ScreenApiError && error.kind === 'not-found') await forgetPairing();
      throw error;
    }

    if (claim.status === 'waiting') return json(200, { status: 'waiting' });
    if (claim.status === 'expired') {
      await forgetPairing();
      return json(200, { status: 'expired' });
    }
    if (claim.deviceToken !== null) {
      await rememberDevice(claim.deviceToken);
      await forgetPairing();
      return await startSession(host, claim.deviceToken);
    }
    // Already collected by an answer that was lost on the way: the device cookie holds the token, or nothing does.
    const device = await deviceFrom(request);
    await forgetPairing();
    return device === null ? json(200, { status: 'expired' }) : await startSession(host, device);
  } catch (error) {
    return screenFailure(error);
  }
}
