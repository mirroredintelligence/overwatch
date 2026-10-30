import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { sealSession, SESSION_COOKIE, type Role, type Session } from '@/lib/auth/session';
import { fakeBackendToken } from '@/test/backendToken';
import { requestWithCookies } from '@/test/cookies';
import type { TestTenant } from '@/test/tenants';

// Helpers that build a request as a signed-in person of a tenant would send it, and the session that
// request carries. They seal with the real `sealSession`, so a test exercises the real unseal, and
// need SESSION_SECRET stubbed (`vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET)`).

export const FIVE_MINUTES = 5 * 60_000;

export function sessionFor(tenant: TestTenant, role: Role, overrides: Partial<Session> = {}): Session {
  return {
    role,
    tenantId: tenant.id,
    host: tenant.host,
    services: [],
    sub: `stf-${tenant.id.padEnd(32, '0')}`.slice(0, 36),
    backendToken: fakeBackendToken({ tenant: tenant.id, role }),
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
    ...overrides,
  };
}

export type RequestAsOptions = {
  method?: string;
  path?: string;
  headers?: Record<string, string>;
  body?: BodyInit;
  /** Cookies besides the session. */
  cookies?: Record<string, string>;
  session?: Partial<Session>;
  /** The host the request is addressed to. Defaults to the tenant's own. */
  host?: string;
  /** A CSRF token to send as cookie and header. Omit to send neither. */
  csrf?: string;
};

/** A request from a signed-in `role` of `tenant`, addressed to the tenant's own host. */
export async function requestAs(tenant: TestTenant, role: Role, options: RequestAsOptions = {}): Promise<Request> {
  const session = sessionFor(tenant, role, options.session);
  const cookies: Record<string, string> = {
    [SESSION_COOKIE]: await sealSession(session),
    ...options.cookies,
  };
  const headers = new Headers(options.headers);
  headers.set('Host', options.host ?? tenant.host);
  if (options.csrf !== undefined) {
    cookies[CSRF_COOKIE] = options.csrf;
    headers.set(CSRF_HEADER, options.csrf);
  }
  const url = `https://${options.host ?? tenant.host}${options.path ?? '/api/bff/session'}`;
  return requestWithCookies(url, cookies, { method: options.method ?? 'GET', headers, body: options.body });
}
