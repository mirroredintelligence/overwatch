import { CSRF_COOKIE, CSRF_HEADER, csrfTokenFor } from '@/lib/auth/csrf';
import { sealSession, SESSION_COOKIE, type Role, type Session } from '@/lib/auth/session';
import { preSessionSubject } from '@/lib/reporter/bff';
import { DEVICE_COOKIE } from '@/lib/reporter/device';
import { fakeBackendToken } from '@/test/backendToken';
import { requestWithCookies } from '@/test/cookies';
import { canary } from '@/test/leak-canary';
import type { TestTenant } from '@/test/tenants';

// Helpers that build a request as a signed-in person of a tenant would send it, and the session that
// request carries. They seal with the real `sealSession`, so a test exercises the real unseal, and
// need SESSION_SECRET stubbed (`vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET)`).

// One expiry for every sample session of a run, so a CSRF token made for one sample session is the
// token of another built the same way (the token is bound to the session's expiry).
const SESSION_EXPIRES = new Date(Date.now() + 3_600_000).toISOString();
/** A fixed nonce, so a test can build the token a session was issued. */
export const CSRF_NONCE = 'N'.repeat(43);

/** The CSRF token issued for a session (the cookie and the header carry this). Needs SESSION_SECRET. */
export function csrfFor(session: Session): string {
  return csrfTokenFor(session, CSRF_NONCE);
}

export function sessionFor(tenant: TestTenant, role: Role, overrides: Partial<Session> = {}): Session {
  // The leak canary now knows this test signs in as this tenant (test/leak-canary.ts).
  canary.expect(tenant.id);
  return {
    role,
    tenantId: tenant.id,
    host: tenant.host,
    services: [],
    sub: `stf-${tenant.id.padEnd(32, '0')}`.slice(0, 36),
    backendToken: fakeBackendToken({ tenant: tenant.id, role }),
    expiresAt: SESSION_EXPIRES,
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
  /**
   * A CSRF token to send as cookie and header: `true` for the one issued to this session, or the text
   * to send. Omit to send neither.
   */
  csrf?: boolean | string;
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
  if (options.csrf !== undefined && options.csrf !== false) {
    const value = options.csrf === true ? csrfFor(session) : options.csrf;
    cookies[CSRF_COOKIE] = value;
    headers.set(CSRF_HEADER, value);
  }
  const url = `https://${options.host ?? tenant.host}${options.path ?? '/api/bff/session'}`;
  return requestWithCookies(url, cookies, { method: options.method ?? 'GET', headers, body: options.body });
}

// ---------------------------------------------------------------------------------------------
// A phone that has no session yet (the reporter's set-up and PIN routes, `preSession`). Its CSRF token
// is bound to the host and the phone's device id (`GET /api/bff/reporter/start` issues it), and the
// tenant is whatever the back end knows from the host: the request carries no tenant and no bearer.

/** A device id as the phone holds it (22 base64url characters). */
export const SAMPLE_DEVICE = 'D'.repeat(22);

/** The CSRF token issued to a phone on a host. Needs SESSION_SECRET. */
export function preSessionCsrfFor(host: string, device: string = SAMPLE_DEVICE): string {
  return csrfTokenFor(preSessionSubject(host, device), CSRF_NONCE);
}

export type PreSessionOptions = {
  method?: string;
  path?: string;
  headers?: Record<string, string>;
  body?: BodyInit;
  cookies?: Record<string, string>;
  /** The host the phone is talking to. Defaults to tenant A's. */
  host?: string;
  device?: string;
  /** `true` for the token issued to this phone on this host, a string to send that text, `false` to send none. */
  csrf?: boolean | string;
};

/** A request from a phone with no session, as the reporter's pages send it. */
export function requestPreSession(options: PreSessionOptions = {}): Request {
  const host = options.host ?? 'tenant-a.example.test';
  const device = options.device ?? SAMPLE_DEVICE;
  const cookies: Record<string, string> = { [DEVICE_COOKIE]: device, ...options.cookies };
  const headers = new Headers(options.headers);
  headers.set('Host', host);
  const csrf = options.csrf ?? true;
  if (csrf !== false) {
    const value = csrf === true ? preSessionCsrfFor(host, device) : csrf;
    cookies[CSRF_COOKIE] = value;
    headers.set(CSRF_HEADER, value);
  }
  return requestWithCookies(`https://${host}${options.path ?? '/api/bff/x'}`, cookies, {
    method: options.method ?? 'POST',
    headers,
    body: options.body,
  });
}
