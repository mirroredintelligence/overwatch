import { randomBytes } from 'node:crypto';
import { toBffError } from '@/lib/bff/errors';
import { issuePending, readPending } from '@/lib/register/pending';
import { sendIdentityCode } from '@/lib/register/backend';
import { bffJson, jsonBody, refuse } from '@/lib/register/requests';
import { normaliseMobile } from '@/lib/register/phone';
import { hostOf, LinkApiError } from '@/lib/links/server';

// The registration code request (W23). No session: the mobile is the only thing that says who this
// is. The back end answers 202 whether or not the number is known, and so does this route. The
// invitation and a device id are kept in a sealed cookie the browser cannot read, for the check.
// The tenant is the host this request was addressed to; the body cannot name one.

const FIELDS = ['phone', 'purpose', 'inviteToken'] as const;
const PURPOSE = 'registration';
const INVITE_TOKEN = /^[A-Za-z0-9_-]{16,128}$/;
const ACCEPTED = { accepted: true, resendAfterSeconds: 60 } as const;
const THROTTLED = 'Too many attempts. Try again later.';
const UNAVAILABLE = 'Sign-in is not available right now. Try again shortly.';

/** A device id the phone holds: 128 bits, base64url (the back end's DEVICE_ID_PATTERN). */
function newDeviceId(): string {
  return randomBytes(16).toString('base64url');
}

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await jsonBody(request, FIELDS);
    const mobile = body !== null && typeof body.phone === 'string' ? normaliseMobile(body.phone) : null;
    const invite = body?.inviteToken;
    if (
      body === null ||
      mobile === null ||
      body.purpose !== PURPOSE ||
      typeof invite !== 'string' ||
      !INVITE_TOKEN.test(invite)
    ) {
      return refuse(400, 'invalid', 'The request was not valid.');
    }

    const earlier = await readPending(request);
    const deviceId = earlier?.deviceId ?? newDeviceId();
    const reply = await sendIdentityCode(hostOf(request), mobile);

    if (reply.status === 202) {
      await issuePending({ deviceId, inviteToken: invite });
      return bffJson(202, ACCEPTED);
    }
    if (reply.status === 429) {
      const retry = reply.retryAfter !== undefined && /^\d{1,6}$/.test(reply.retryAfter) ? reply.retryAfter : '600';
      return refuse(429, 'throttled', THROTTLED, { 'Retry-After': retry });
    }
    return refuse(503, 'unavailable', UNAVAILABLE);
  } catch (error) {
    // A back end that cannot be reached is a 503 with no detail, never a 500 that names the error.
    if (error instanceof LinkApiError) return refuse(503, 'unavailable', UNAVAILABLE);
    return toBffError(error);
  }
}
