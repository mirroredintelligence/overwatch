import { withBff } from '@/lib/bff/handler';
import { fhirFetch, FhirError } from '@/lib/fhir/client';
import { idempotencyKeyOf, jsonBody } from '@/lib/lead/bffInput';
import { readChangeNumber } from '@/lib/lead/changeNumber';
import { parametersOf, partValue } from '@/lib/lead/parameters';
import { postsFrom } from '@/lib/lead/reporters';

// A change of a reporter's number for leave or cover (W18). Lead only, CSRF on the POST, the Idempotency-Key is
// passed on. The back end changes a post by its role id, which the browser never holds: the route finds the
// service's post by reading the posts of that service, then calls $change-number on it. A service with no post
// is a 404. The answer names the last four digits and the cover end, never the number.

const NO_STORE = { 'Cache-Control': 'no-store' };

function notFound(): FhirError {
  return new FhirError(404, {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'not-found', diagnostics: 'not found' }],
  });
}

const post = withBff(
  async (request, session) => {
    const key = idempotencyKeyOf(request);
    const change = readChangeNumber(await jsonBody(request));
    const { data: listed } = await fhirFetch<unknown>(`/lead/reporters?service=${encodeURIComponent(change.serviceId)}`, {
      root: true,
      token: session.backendToken,
      cache: 'no-store',
    });
    const post = postsFrom(listed).find((item) => item.serviceId === change.serviceId);
    if (post === undefined) throw notFound();

    const { data } = await fhirFetch<unknown>(`/PractitionerRole/${encodeURIComponent(post.roleId)}/$change-number`, {
      method: 'POST',
      body: parametersOf([
        { name: 'mobile', valueString: change.newNumber },
        { name: 'duration', valueCode: change.until },
      ]),
      token: session.backendToken,
      idempotencyKey: key,
    });
    const ending = partValue(data, 'numberEnding');
    const coverUntil = partValue(data, 'coverUntil');
    if (typeof ending !== 'string') throw new Error('The back end did not name the number that was set.');
    return Response.json(
      { numberEnding: ending, coverUntil: typeof coverUntil === 'string' ? coverUntil : null },
      { headers: NO_STORE },
    );
  },
  { roles: ['lead'] },
);

export const POST = (request: Request) => post(request, undefined);
