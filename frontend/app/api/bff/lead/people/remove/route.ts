import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, jsonBody } from '@/lib/lead/bffInput';
import { parametersOf, partValue } from '@/lib/lead/parameters';

// Removes a person's access (W42): the back end's $remove on a reporter's post (U37). Lead only, CSRF. The post is
// named by its role id, which the lead's list gives; a value that is not a role id is refused here and never
// matched. The answer gives the counts the back end gives (roles ended, devices signed out, services left without a
// reporter). Nothing of the person is returned.

const REASONS = ['left-service', 'changed-role', 'lost-phone', 'other'] as const;
const ROLE_ID = /^[A-Za-z0-9.-]{1,64}$/;

const post = withBff(
  async (request, session) => {
    const key = idempotencyKeyOf(request);
    const body = (await jsonBody(request)) as { person?: unknown; reason?: unknown } | null;
    if (typeof body?.person !== 'string' || !ROLE_ID.test(body.person)) throw invalidRequest();
    if (!(REASONS as readonly unknown[]).includes(body.reason)) throw invalidRequest();
    const { data } = await fhirFetch<unknown>(`/PractitionerRole/${encodeURIComponent(body.person)}/$remove`, {
      method: 'POST',
      body: parametersOf([{ name: 'reason', valueCode: body.reason as string }]),
      token: session.backendToken,
      idempotencyKey: key,
    });
    const count = (name: string) => {
      const value = partValue(data, name);
      return typeof value === 'number' ? value : 0;
    };
    return Response.json(
      {
        rolesEnded: count('rolesEnded'),
        devicesRevoked: count('devicesRevoked'),
        servicesWithoutReporter: count('servicesWithoutReporter'),
      },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { roles: ['lead'] },
);

export const POST = (request: Request) => post(request, undefined);
