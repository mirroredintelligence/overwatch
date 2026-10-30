import { TENANTS } from '@/test/tenants';
import { requestAs, sessionFor as tenantSessionFor } from '@/test/requests';
import type { Role, Session } from '@/lib/auth/session';

// Builds requests for the lead BFF route tests: a person of tenant A signed in on tenant A's host, and
// the CSRF pair issued to that session when asked. The session is sealed with the real `sealSession`
// (test/requests.ts), so it carries the tenant and the host the BFF now requires.

export const LEAD_TENANT = TENANTS.A;

export function sessionFor(role: Role): Session {
  return tenantSessionFor(LEAD_TENANT, role, { sub: 'user-1', backendToken: 'token-for-the-lead' });
}

export async function leadRequest(
  url: string,
  role: Role | null,
  options: { method?: string; csrf?: boolean; key?: string | null; body?: unknown } = {},
): Promise<Request> {
  const headers: Record<string, string> = {};
  if (options.key) headers['Idempotency-Key'] = options.key;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  const path = new URL(url).pathname + new URL(url).search;
  if (role === null) {
    // No session: a request to the tenant's host with nothing sealed.
    headers.Host = LEAD_TENANT.host;
    return new Request(`https://${LEAD_TENANT.host}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  }
  return requestAs(LEAD_TENANT, role, {
    method: options.method ?? 'GET',
    path,
    headers,
    csrf: options.csrf ? true : undefined,
    session: { sub: 'user-1', backendToken: 'token-for-the-lead' },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
}
