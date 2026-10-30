import { withBff } from '@/lib/bff/handler';
import { FhirError, fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, jsonBody } from '@/lib/lead/bffInput';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { notBuilt } from '@/lib/lead/notBuilt';
import { parametersOf, partValue } from '@/lib/lead/parameters';

// Invites a reporter (W43): the back end's $invite-reporter (R10). Lead only, CSRF. The answer names the ids
// and the last four digits of the number, never the number. A service outside the pilot is a 409 with the code
// "not-in-pilot", so the page can say what it means. The list of invitations is not on the back end yet: 501.

const PILOT_REFUSAL = 'Only services in the pilot can be invited';
const CHANNELS = ['push', 'text', 'email'] as const;
const ROLE_MAX = 200;
const SERVICE_ID = /^[A-Za-z0-9.-]{1,64}$/;

const get = withBff(async () => notBuilt(), { roles: ['lead'] });

const post = withBff(
  async (request, session) => {
    const key = idempotencyKeyOf(request);
    const body = (await jsonBody(request)) as Record<string, unknown> | null;
    const serviceId = body?.serviceId;
    const role = body?.role;
    const phone = body?.phone;
    const channel = typeof body?.channel === 'string' ? body.channel : '';
    if (typeof serviceId !== 'string' || !SERVICE_ID.test(serviceId)) throw invalidRequest();
    if (typeof role !== 'string' || role.trim() === '' || role.length > ROLE_MAX) throw invalidRequest();
    if (typeof phone !== 'string' || !isUkMobile(phone)) throw invalidRequest();
    if (!(CHANNELS as readonly string[]).includes(channel)) throw invalidRequest();

    let data: unknown;
    try {
      ({ data } = await fhirFetch<unknown>('/Task/$invite-reporter', {
        method: 'POST',
        body: parametersOf([
          { name: 'service', valueString: `HealthcareService/${serviceId}` },
          { name: 'role', valueString: role.trim() },
          { name: 'mobile', valueString: phone },
          { name: 'suggestedChannel', valueCode: channel },
        ]),
        token: session.backendToken,
        idempotencyKey: key,
      }));
    } catch (error) {
      if (error instanceof FhirError && error.status === 409 && error.outcome.issue?.[0]?.diagnostics === PILOT_REFUSAL) {
        throw new FhirError(409, {
          resourceType: 'OperationOutcome',
          issue: [{ severity: 'error', code: 'not-in-pilot', diagnostics: 'The service is not in the pilot.' }],
        });
      }
      throw error;
    }

    const invitationId = partValue(data, 'invitationId');
    const numberEnding = partValue(data, 'numberEnding');
    const expiresAt = partValue(data, 'expiresAt');
    return Response.json(
      {
        invitationId: typeof invitationId === 'string' ? invitationId : null,
        numberEnding: typeof numberEnding === 'string' ? numberEnding : null,
        expiresAt: typeof expiresAt === 'string' ? expiresAt : null,
      },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { roles: ['lead'] },
);

export const GET = (request: Request) => get(request, undefined);
export const POST = (request: Request) => post(request, undefined);
