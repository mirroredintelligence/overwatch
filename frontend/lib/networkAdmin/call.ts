import { fhirFetch } from '@/lib/fhir/client';

// The calls the network administration BFF routes make to the back end's `/network-admin` routes (at the
// app root, not under /fhir). The token is the signed-in person's own and the tenant is the one inside it:
// nothing here names one. A network or a record is named only in the path, after the routes have checked
// it. A POST always says it is JSON, with `{}` for a body that is empty, because the back end refuses a
// write that does not. The back end has no idempotency key: each command is repeatable by its state.

type Bearer = { backendToken: string };

export async function adminRead(session: Bearer, path: string): Promise<unknown> {
  const { data } = await fhirFetch<unknown>(path, { root: true, token: session.backendToken, cache: 'no-store' });
  return data;
}

export async function adminWrite(session: Bearer, path: string, body?: unknown): Promise<unknown> {
  const { data } = await fhirFetch<unknown>(path, { root: true, method: 'POST', token: session.backendToken, body: body ?? {}, cache: 'no-store' });
  return data;
}

export const NO_STORE = { 'Cache-Control': 'no-store' };
