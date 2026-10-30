// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_HEADER } from '@/lib/auth/csrf';
import { CSRF_COOKIE } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { cookiesMock, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { POST } from './route';
import { csrfOf } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = csrfOf(TENANTS.A, 'sess-1');
const URL_ = `https://${TENANTS.A.host}/api/bff/reporter/channel`;

const session: Session = {
  role: 'reporter',
  tenantId: TENANTS.A.id,
  host: TENANTS.A.host,
  services: ['svc-1'],
  sub: 'sess-1',
  backendToken: 'sess-1',
  expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  resetCookieWrites();
  cookiesMock.mockClear();
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/reporter/channel', () => {
  it('needs a reporter session', async () => {
    const response = await POST(
      requestWithCookies(URL_, { [CSRF_COOKIE]: CSRF }, { method: 'POST', headers: { [CSRF_HEADER]: CSRF }, body: '{"channel":"text"}' }),
      { params: Promise.resolve({}) },
    );
    expect(response.status).toBe(401);
  });

  it('refuses a request without the csrf header', async () => {
    const cookie = await sealSession(session);
    const response = await POST(
      requestWithCookies(URL_, { [SESSION_COOKIE]: cookie, [CSRF_COOKIE]: CSRF }, { method: 'POST', body: '{"channel":"text"}' }),
      { params: Promise.resolve({}) },
    );
    expect(response.status).toBe(403);
  });

  it('answers not-built (503) with a valid session and csrf until the back end has the route', async () => {
    const cookie = await sealSession(session);
    const response = await POST(
      requestWithCookies(URL_, { [SESSION_COOKIE]: cookie, [CSRF_COOKIE]: CSRF }, { method: 'POST', headers: { [CSRF_HEADER]: CSRF }, body: '{"channel":"text"}' }),
      { params: Promise.resolve({}) },
    );
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: 'not-built' });
  });
});
