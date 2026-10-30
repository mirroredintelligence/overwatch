import { requestHost } from '@/lib/auth/host';
import { isTenantId } from '@/lib/auth/ids';
import { preSession } from '@/lib/reporter/bff';
import { ensureDevice } from '@/lib/reporter/device';
import { identityCall } from '@/lib/reporter/identity';
import { startReporterSession } from '@/lib/reporter/session';

// POST /api/bff/identity/pin/verify (W34, W35): sign the reporter in with the PIN. On success the
// BFF seals a reporter session and answers {ok:true} only: the back end's session id never reaches
// the browser. A wrong PIN answers the tries left; five wrong tries answer locked; a PIN that needs
// a text code first answers reverify. The session is for the tenant the back end answers with (a
// valid tenant id, never a network id) and for the host the phone came to; an answer with no tenant
// signs nobody in (fail closed: the session has no guessed tenant). The back end's PIN session id is
// exchanged for a 30-minute reporter token before anything is sealed (DEC-792): the token is the
// bearer, the PIN session stays beside it in the sealed cookie for the renewal, and a token that is
// not for this tenant and phone, or no token, signs nobody in.

const PIN = /^\d{6}$/;
const NO_STORE = { 'Cache-Control': 'no-store' };

type BackEnd = {
  signedIn?: boolean;
  sessionId?: string;
  tenant?: unknown;
  triesLeft?: number;
  needsTextCode?: boolean;
};

export const POST = preSession(async (request) => {
  const body = (await request.json().catch(() => undefined)) as { pin?: unknown } | undefined;
  if (typeof body?.pin !== 'string' || !PIN.test(body.pin)) {
    return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
  }
  const deviceId = await ensureDevice(request);
  const reply = await identityCall(request, { method: 'POST', path: '/identity/pin/verify', body: { deviceId, pin: body.pin } });
  const answer = (reply.body ?? {}) as BackEnd;

  if (reply.status === 200 && answer.signedIn === true && typeof answer.sessionId === 'string') {
    const host = requestHost(request);
    if (host === null || !isTenantId(answer.tenant)) {
      return Response.json({ code: 'unavailable' }, { status: 503, headers: NO_STORE });
    }
    const started = await startReporterSession({ sessionId: answer.sessionId, tenantId: answer.tenant, host, device: deviceId });
    if (started !== 'started') return Response.json({ code: 'unavailable' }, { status: 503, headers: NO_STORE });
    return Response.json({ ok: true }, { headers: NO_STORE });
  }
  if (reply.status === 423) return Response.json({ locked: true }, { headers: NO_STORE });
  if (reply.status === 403 && answer.needsTextCode === true) {
    return Response.json({ reverify: true }, { headers: NO_STORE });
  }
  if (reply.status === 403 && typeof answer.triesLeft === 'number') {
    return Response.json({ ok: false, triesLeft: answer.triesLeft }, { headers: NO_STORE });
  }
  return Response.json({ code: 'unavailable' }, { status: 503, headers: NO_STORE });
});
