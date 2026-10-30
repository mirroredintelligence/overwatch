import { createSession } from '@/lib/auth/session';
import { toBffError } from '@/lib/bff/errors';
import { signInRegistrant, verifyIdentityCode } from '@/lib/register/backend';
import { clearPending, readPending } from '@/lib/register/pending';
import { normaliseMobile } from '@/lib/register/phone';
import { bffJson, jsonBody, refuse } from '@/lib/register/requests';
import { hostOf, LinkApiError } from '@/lib/links/server';

// The registration code check (W23). On a right code the back end records the code on this device;
// the applicant is then signed in as a reporter with the registration the invitation names. The
// session is sealed into an HTTP-only cookie, and the JSON answer carries no token.

const FIELDS = ['phone', 'code'] as const;
const UNAVAILABLE = 'Sign-in is not available right now. Try again shortly.';
const CODE = /^\d{6}$/;
const EXPIRED = 'That code has expired. Ask for a new code.';
const WRONG = 'That code is not right.';
const LOCKED_OR_LAPSED = /ask for a new code/i;

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
    const mobile = body !== null && typeof body.phone === 'string' ? normaliseMobile(body.phone) : null;
    if (body === null || mobile === null || typeof body.code !== 'string' || !CODE.test(body.code)) {
      return refuse(400, 'invalid', 'The request was not valid.');
    }

    const pending = await readPending(request);
    if (pending === null) return refuse(410, 'expired', EXPIRED);

    const reply = await verifyIdentityCode({
      host: hostOf(request),
      mobile,
      code: body.code,
      deviceId: pending.deviceId,
    });

    if (reply.status === 400) {
      const text = diagnostics(reply.body);
      if (LOCKED_OR_LAPSED.test(text)) return refuse(410, 'expired', EXPIRED);
      return refuse(400, 'wrong-code', WRONG);
    }
    if (reply.status === 409) return refuse(409, 'device-refused', 'This phone cannot be set up with this code. Start again on this phone.');
    if (reply.status === 429) return refuse(429, 'throttled', 'Too many attempts. Try again later.');
    if (reply.status !== 200) return refuse(503, 'unavailable', 'Sign-in is not available right now. Try again shortly.');

    const { registrationId, session } = await signInRegistrant({
      mobile,
      deviceId: pending.deviceId,
      inviteToken: pending.inviteToken,
    });
    await createSession(session);
    await clearPending();
    return bffJson(200, { registrationId });
  } catch (error) {
    // A back end that cannot be reached is a 503 with no detail, never a 500 that names the error.
    if (error instanceof LinkApiError) return refuse(503, 'unavailable', UNAVAILABLE);
    return toBffError(error);
  }
}
