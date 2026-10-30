import { toBffError } from '@/lib/bff/errors';
import { readInvitation } from '@/lib/register/backend';
import { bffJson, jsonBody, refuse } from '@/lib/register/requests';
import { hostOf, LinkApiError } from '@/lib/links/server';

// POST /api/bff/identity/invitation (W23). The registration page reads the link before it asks for a
// code: the service, and the last three digits of the number the code will go to. The back end reads
// the link in the request host's tenant; the body names nothing else. Nothing here is sealed: the
// answer holds no tenant, no person and no whole number.

const FIELDS = ['inviteToken'] as const;
const INVITE_TOKEN = /^[A-Za-z0-9_-]{16,128}$/;
const NOT_FOUND = 'We could not find an invitation for this link.';
const UNAVAILABLE = 'Sign-in is not available right now. Try again shortly.';
const ENDING = /^\d{3}$/;

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await jsonBody(request, FIELDS);
    const invite = body?.inviteToken;
    if (body === null || typeof invite !== 'string' || !INVITE_TOKEN.test(invite)) {
      return refuse(400, 'invalid', 'The request was not valid.');
    }

    const reply = await readInvitation(hostOf(request), invite);
    if (reply.status === 404) return refuse(404, 'not-found', NOT_FOUND);
    if (reply.status !== 200) return refuse(503, 'unavailable', UNAVAILABLE);

    const answer = reply.body as Record<string, unknown> | null;
    if (answer?.state === 'expired' || answer?.state === 'used') return bffJson(200, { state: answer.state });
    if (
      answer?.state !== 'open' ||
      typeof answer.serviceName !== 'string' ||
      typeof answer.numberEnding !== 'string' ||
      !ENDING.test(answer.numberEnding) ||
      typeof answer.expiresAt !== 'string'
    ) {
      return refuse(503, 'unavailable', UNAVAILABLE);
    }
    return bffJson(200, {
      state: 'open',
      serviceName: answer.serviceName,
      numberEnding: answer.numberEnding,
      expiresAt: answer.expiresAt,
    });
  } catch (error) {
    // A back end that cannot be reached is a 503 with no detail, never a 500 that names the error.
    if (error instanceof LinkApiError) return refuse(503, 'unavailable', UNAVAILABLE);
    return toBffError(error);
  }
}
