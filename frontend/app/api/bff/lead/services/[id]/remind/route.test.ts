// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { POST } from './route';
import { csrfOf } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = csrfOf(TENANTS.A, 'user-1');
const URL_ = `https://${TENANTS.A.host}/api/bff/lead/services/s-virtual-ward/remind`;

function session(role: Role): Session {
  return {
    role,
    tenantId: TENANTS.A.id,
    host: TENANTS.A.host,
    services: [],
    sub: 'user-1',
    backendToken: 'token-for-the-lead',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function post(role: Role, options: { csrf: boolean }) {
  const cookies: Record<string, string> = { [SESSION_COOKIE]: await sealSession(session(role)) };
  const headers: Record<string, string> = {};
  if (options.csrf) {
    cookies[CSRF_COOKIE] = CSRF;
    headers[CSRF_HEADER] = CSRF;
  }
  return POST(requestWithCookies(URL_, cookies, { method: 'POST', headers }), {
    params: Promise.resolve({ id: 's-virtual-ward' }),
  });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('POST /api/bff/lead/services/[id]/remind', () => {
  it('answers 403 without the CSRF header, even for a lead', async () => {
    const response = await post('lead', { csrf: false });
    expect(response.status).toBe(403);
    expect(((await response.json()) as { code: string }).code).toBe('csrf');
  });

  it('answers 403 to an advisor even with the CSRF header', async () => {
    expect((await post('advisor', { csrf: true })).status).toBe(403);
  });

  it('answers 501 for a lead with the CSRF header until the back end has a reminder route', async () => {
    const response = await post('lead', { csrf: true });
    expect(response.status).toBe(501);
    expect(((await response.json()) as { code: string }).code).toBe('not-built');
  });
});
