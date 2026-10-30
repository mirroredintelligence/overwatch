import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies } from '@/test/cookies';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';

// Builds requests for the lead BFF route tests: a sealed session for a role, and the CSRF pair when asked.

export const LEAD_CSRF = 'csrf-token-for-the-test-0123456789abcdefghij';

export function sessionFor(role: Role): Session {
  return {
    role,
    services: [],
    sub: 'user-1',
    backendToken: 'token-for-the-lead',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

export async function leadRequest(
  url: string,
  role: Role | null,
  options: { method?: string; csrf?: boolean; key?: string | null; body?: unknown } = {},
): Promise<Request> {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(sessionFor(role));
  const headers: Record<string, string> = {};
  if (options.csrf) {
    cookies[CSRF_COOKIE] = LEAD_CSRF;
    headers[CSRF_HEADER] = LEAD_CSRF;
  }
  if (options.key) headers['Idempotency-Key'] = options.key;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  return requestWithCookies(url, cookies, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
}
