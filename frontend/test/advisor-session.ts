import type { Role, Session } from '@/lib/auth/session';
import { requestAs, sessionFor as tenantSessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

// Builds requests for the advisor BFF route tests (W8A): a person of tenant A signed in on tenant A's
// host, the CSRF pair issued to that session when asked. The session is sealed with the real
// `sealSession` (test/requests.ts), and the back-end token is the one every assertion looks for.

export const ADVISOR_TENANT = TENANTS.A;
export const ADVISOR_TOKEN = 'token-for-the-advisor';

export function advisorSession(role: Role): Session {
  return tenantSessionFor(ADVISOR_TENANT, role, { sub: 'user-1', backendToken: ADVISOR_TOKEN });
}

export type AdvisorRequestOptions = {
  method?: string;
  csrf?: boolean | string;
  key?: string | null;
  ifMatch?: string | null;
  body?: unknown;
  headers?: Record<string, string>;
};

export async function advisorRequest(url: string, role: Role | null, options: AdvisorRequestOptions = {}): Promise<Request> {
  const headers: Record<string, string> = { ...options.headers };
  if (options.key) headers['Idempotency-Key'] = options.key;
  if (options.ifMatch) headers['If-Match'] = options.ifMatch;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  const path = new URL(url).pathname + new URL(url).search;
  if (role === null) {
    headers.Host = ADVISOR_TENANT.host;
    return new Request(`https://${ADVISOR_TENANT.host}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  }
  return requestAs(ADVISOR_TENANT, role, {
    method: options.method ?? 'GET',
    path,
    headers,
    csrf: options.csrf === false ? undefined : options.csrf,
    session: { sub: 'user-1', backendToken: ADVISOR_TOKEN },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
}
