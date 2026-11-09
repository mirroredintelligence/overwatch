import { hostOf } from '@/lib/links/server';
import { json, refuse, screenFailure } from '@/lib/screens/answers';
import { rememberPairing } from '@/lib/screens/cookies';
import { isSameOriginRequest } from '@/lib/screens/origin';
import { startPairing } from '@/lib/screens/server';
import { isTenantLetters } from '@/lib/tenant/hint';

// The wall display asks for a code. No session. The organisation is the host's when a tenant has a domain of its own,
// and otherwise the letters the display's address carried (`?org=`, DEC-1354), sent in the body: they only say where
// the pairing is made, and the code is then claimed by a signed-in lead of that organisation.
// The secret that proves this display is the one that asked stays in a sealed cookie.

async function organisationOf(request: Request): Promise<string | null> {
  try {
    const text = await request.text();
    if (text.length === 0 || text.length > 200) return null;
    const body: unknown = JSON.parse(text);
    const org = typeof body === 'object' && body !== null ? (body as Record<string, unknown>).org : undefined;
    return isTenantLetters(org) ? org : null;
  } catch {
    return null;
  }
}

export async function POST(request: Request): Promise<Response> {
  if (!isSameOriginRequest(request)) return refuse(403, 'forbidden', 'You cannot do that.');
  try {
    const org = await organisationOf(request);
    const started = await startPairing(hostOf(request), org ?? undefined);
    await rememberPairing({ pairingId: started.pairingId, screenSecret: started.screenSecret });
    return json(201, { pairingId: started.pairingId, code: started.code, expiresAt: started.expiresAt });
  } catch (error) {
    return screenFailure(error);
  }
}
