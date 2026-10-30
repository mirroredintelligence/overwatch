import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { requestWithCookies } from '@/test/cookies';
import { csrfOf } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

// A signed-in applicant's (or lead's) request to a BFF route: a sealed session on the tenant's host,
// the CSRF cookie and header bound to that session. Sample values only.

export const APPLICANT_SUB = 'person-sample-1';
export const BACKEND_TOKEN = 'backend-token-sample-value';

export async function sessionCookie(role: Session['role'] = 'reporter', overrides: Partial<Session> = {}): Promise<string> {
  return sealSession({
    role,
    tenantId: TENANTS.A.id,
    host: TENANTS.A.host,
    services: [],
    sub: APPLICANT_SUB,
    backendToken: BACKEND_TOKEN,
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
    ...overrides,
  });
}

/** A request with the session cookie; an unsafe method also carries the CSRF header and cookie. */
export async function callerRequest(
  url: string,
  role: Session['role'] = 'reporter',
  options: { method?: string; body?: unknown; csrf?: boolean; idempotencyKey?: string } = {},
): Promise<Request> {
  const method = options.method ?? 'GET';
  const csrf = csrfOf(TENANTS.A, APPLICANT_SUB);
  const cookies: Record<string, string> = { [SESSION_COOKIE]: await sessionCookie(role) };
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.idempotencyKey !== undefined) headers['Idempotency-Key'] = options.idempotencyKey;
  if (method !== 'GET' && options.csrf !== false) {
    cookies[CSRF_COOKIE] = csrf;
    headers[CSRF_HEADER] = csrf;
  }
  return requestWithCookies(url, cookies, {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
}
