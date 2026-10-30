import { createSession, type Session } from '@/lib/auth/session';
import { requestHost } from '@/lib/auth/host';
import { toBffError } from '@/lib/bff/errors';
import { verifyRegistrationCode } from '@/lib/register/backend';
import { clearPending, readPending } from '@/lib/register/pending';
import { reporterSessionFor } from '@/lib/register/signin';
import { bffJson, jsonBody, refuse } from '@/lib/register/requests';
import { hostOf, LinkApiError } from '@/lib/links/server';

// The registration code check (W23, DEC-900 to DEC-902). The invitation and the device come from the
// sealed pending cookie, never from the body, which holds the code and nothing else. On a right code
// the back end records the code on this device and answers a reporter token for the tenant it bound
// from the host. The BFF seals a session that carries that tenant and this host, and answers the
// registration id. A session the BFF cannot vouch for is refused (503) and nothing is written.

const FIELDS = ['code'] as const;
const CODE = /^\d{6}$/;
const EXPIRED = 'That code has expired. Ask for a new code.';
const WRONG = 'That code is not right. Check it and try again.';
const NO_INVITATION = 'We could not find an invitation for this number. Ask the shift lead to check it.';
const DEVICE_REFUSED = 'This phone cannot be set up with this code. Start again on this phone.';
const THROTTLED = 'Too many attempts. Try again later.';
const UNAVAILABLE = 'Sign-in is not available right now. Try again shortly.';
const LAPSED = /ask for a new code/i;

function diagnostics(body: unknown): string {
  if (typeof body !== 'object' || body === null) return '';
  const issue = (body as { issue?: unknown }).issue;
  if (!Array.isArray(issue) || issue.length === 0) return '';
  const first = issue[0] as { diagnostics?: unknown };
  return typeof first.diagnostics === 'string' ? first.diagnostics : '';
}

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await jsonBody(request, FIELDS);
    if (body === null || typeof body.code !== 'string' || !CODE.test(body.code)) {
      return refuse(400, 'invalid', 'The request was not valid.');
    }

    const pending = await readPending(request);
    if (pending === null || pending.inviteToken === undefined) return refuse(410, 'expired', EXPIRED);

    const reply = await verifyRegistrationCode({
      host: hostOf(request),
      invitation: pending.inviteToken,
      code: body.code,
      deviceId: pending.deviceId,
    });

    if (reply.status === 200) {
      const answer = reply.body as Record<string, unknown> | null;
      const session: Session | null =
        answer !== null && typeof answer.registrationId === 'string'
          ? reporterSessionFor(answer, { host: requestHost(request), deviceId: pending.deviceId, now: new Date() })
          : null;
      if (session === null || answer === null || typeof answer.registrationId !== 'string') {
        return refuse(503, 'unavailable', UNAVAILABLE);
      }
      await createSession(session);
      await clearPending();
      return bffJson(200, { registrationId: answer.registrationId });
    }
    if (reply.status === 400) {
      if (LAPSED.test(diagnostics(reply.body))) return refuse(410, 'expired', EXPIRED);
      return refuse(400, 'wrong-code', WRONG);
    }
    if (reply.status === 404) return refuse(403, 'no-invitation', NO_INVITATION);
    if (reply.status === 409) return refuse(409, 'device-refused', DEVICE_REFUSED);
    if (reply.status === 429) return refuse(429, 'throttled', THROTTLED);
    return refuse(503, 'unavailable', UNAVAILABLE);
  } catch (error) {
    // A back end that cannot be reached is a 503 with no detail, never a 500 that names the error.
    if (error instanceof LinkApiError) return refuse(503, 'unavailable', UNAVAILABLE);
    return toBffError(error);
  }
}
