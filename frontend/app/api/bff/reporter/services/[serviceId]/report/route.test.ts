// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
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
const URL_ = `https://${TENANTS.A.host}/api/bff/reporter/services/svc-1/report`;

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

async function call(serviceId: string, body: string, withSession = true) {
  const cookies: Record<string, string> = { [CSRF_COOKIE]: CSRF };
  if (withSession) cookies[SESSION_COOKIE] = await sealSession(session);
  return POST(
    requestWithCookies(URL_.replace('svc-1', serviceId), cookies, {
      method: 'POST',
      headers: { [CSRF_HEADER]: CSRF },
      body,
    }),
    { params: Promise.resolve({ serviceId }) },
  );
}

describe('POST /api/bff/reporter/services/[serviceId]/report', () => {
  it('needs a reporter session', async () => {
    expect((await call('svc-1', '{"kind":"confirm"}', false)).status).toBe(401);
  });

  it('answers the same 404 for a service the reporter does not act for, as for an unknown one', async () => {
    const response = await call('svc-9', '{"kind":"confirm"}');
    expect(response.status).toBe(404);
  });

  it('refuses an unknown kind and a figure that is not a whole number', async () => {
    expect((await call('svc-1', '{"kind":"delete"}')).status).toBe(400);
    expect((await call('svc-1', '{"kind":"number","value":2.5}')).status).toBe(400);
  });

  it('answers not-built (503) for a valid report until the back end has the reporter route', async () => {
    const response = await call('svc-1', '{"kind":"number","value":4}');
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain('svc-1');
  });
});
