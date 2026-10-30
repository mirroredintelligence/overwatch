// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { sealSession } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { POST } from './route';
import { csrfOf } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = csrfOf(TENANTS.A, 'sample-sub');

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', 'http://backend.test/fhir');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

const owner = () =>
  sealSession({
    role: 'owner',
    tenantId: TENANTS.A.id,
    host: TENANTS.A.host,
    services: [],
    sub: 'sample-sub',
    backendToken: 'sample-token',
    expiresAt: new Date(Date.now() + 3600_000).toISOString(),
  });

describe('POST /api/bff/criteria/[serviceId]/submit', () => {
  it('refuses a change with no CSRF header, and calls nothing upstream', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const cookie = await owner();
    const request = requestWithCookies(
      `https://${TENANTS.A.host}/api/bff/criteria/s1/submit`,
      { diucs_session: cookie },
      { method: 'POST', body: JSON.stringify({ reason: 'Youngest age', reviewInMonths: 6 }), headers: { 'Content-Type': 'application/json' } },
    );
    const response = await POST(request, { params: Promise.resolve({ serviceId: 's1' }) });
    expect(response.status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('refuses a review period other than 3, 6 or 12 months, with 400 and no upstream call', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const cookie = await owner();
    const request = requestWithCookies(
      `https://${TENANTS.A.host}/api/bff/criteria/s1/submit`,
      { diucs_session: cookie, diucs_csrf: CSRF },
      {
        method: 'POST',
        body: JSON.stringify({ reason: 'Youngest age', reviewInMonths: 4, accepts: [] }),
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF, 'Idempotency-Key': 'key-submit-1' },
      },
    );
    const response = await POST(request, { params: Promise.resolve({ serviceId: 's1' }) });
    expect(response.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
