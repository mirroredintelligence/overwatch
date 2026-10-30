import { hostOf } from '@/lib/links/server';
import { json, refuse, screenFailure } from '@/lib/screens/answers';
import { rememberPairing } from '@/lib/screens/cookies';
import { isSameOriginRequest } from '@/lib/screens/origin';
import { startPairing } from '@/lib/screens/server';

// The wall display asks for a code. No session, and nothing is read from the request but the host
// it was opened on, which names the tenant (DEC-134 item 3): not the body, the query or any header.
// The secret that proves this display is the one that asked stays in a sealed cookie.

export async function POST(request: Request): Promise<Response> {
  if (!isSameOriginRequest(request)) return refuse(403, 'forbidden', 'You cannot do that.');
  try {
    const started = await startPairing(hostOf(request));
    await rememberPairing({ pairingId: started.pairingId, screenSecret: started.screenSecret });
    return json(201, { pairingId: started.pairingId, code: started.code, expiresAt: started.expiresAt });
  } catch (error) {
    return screenFailure(error);
  }
}
