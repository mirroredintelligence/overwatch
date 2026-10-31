import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, jsonBody } from '@/lib/lead/bffInput';

// The calls the tenant administrator's BFF routes make to the back end's `/tenant` routes (at the app root,
// not under /fhir). The token is the signed-in person's own and the tenant is the one inside it: nothing
// here names one. A write passes the Idempotency-Key the back end requires; a POST or PUT always says
// `application/json`, with `{}` for a body that is empty, because the back end refuses a write that does not.

export { invalidRequest, jsonBody };

type Bearer = { backendToken: string };

export async function tenantRead(session: Bearer, path: string): Promise<unknown> {
  const { data } = await fhirFetch<unknown>(path, { root: true, token: session.backendToken, cache: 'no-store' });
  return data;
}

export async function tenantWrite(
  session: Bearer,
  request: Request,
  method: 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<unknown> {
  const key = idempotencyKeyOf(request);
  const { data } = await fhirFetch<unknown>(path, {
    root: true,
    method,
    token: session.backendToken,
    idempotencyKey: key,
    body: method === 'DELETE' ? undefined : (body ?? {}),
    cache: 'no-store',
  });
  return data;
}

export const NO_STORE = { 'Cache-Control': 'no-store' };

export function noContent(): Response {
  return new Response(null, { status: 204, headers: NO_STORE });
}
