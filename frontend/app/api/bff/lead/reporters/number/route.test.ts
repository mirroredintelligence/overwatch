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
const URL_ = `https://${TENANTS.A.host}/api/bff/lead/reporters/number`;

function session(role: Role): Session {
  return { role, tenantId: TENANTS.A.id, host: TENANTS.A.host, services: [], sub: 'user-1', backendToken: 'token-for-the-lead', expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
}

async function post(role: Role, body: unknown) {
  const cookies: Record<string, string> = { [SESSION_COOKIE]: await sealSession(session(role)), [CSRF_COOKIE]: CSRF };
  return POST(
    requestWithCookies(URL_, cookies, {
      method: 'POST',
      headers: { [CSRF_HEADER]: CSRF, 'Idempotency-Key': 'change-key-0001', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  );
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('POST /api/bff/lead/reporters/number', () => {
  it('answers 403 to an advisor', async () => {
    expect((await post('advisor', { serviceId: 's-1', newNumber: '07700 900456', until: 'today' })).status).toBe(403);
  });

  it.each([
    ['a number that is not a UK mobile', { serviceId: 's-1', newNumber: '0123', until: 'today' }],
    ['an unknown cover', { serviceId: 's-1', newNumber: '07700 900456', until: 'next-year' }],
    ['no service', { newNumber: '07700 900456', until: 'today' }],
  ])('answers 400 for %s', async (_label, body) => {
    const response = await post('lead', body);
    expect(response.status).toBe(400);
    expect(await response.text()).not.toContain('0123');
  });

  it('answers 501 for a valid change until the back end can name the service role, and echoes no number', async () => {
    const response = await post('lead', { serviceId: 's-1', newNumber: '07700 900456', until: 'this-week' });
    expect(response.status).toBe(501);
    const text = await response.text();
    expect(text).not.toContain('900456');
    expect(text).not.toContain('0456');
  });
});
