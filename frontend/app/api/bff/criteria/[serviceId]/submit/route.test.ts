// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { sealSession } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { POST } from './route';

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
      'https://app.test/api/bff/criteria/s1/submit',
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
      'https://app.test/api/bff/criteria/s1/submit',
      { diucs_session: cookie, diucs_csrf: 'csrf-sample' },
      {
        method: 'POST',
        body: JSON.stringify({ reason: 'Youngest age', reviewInMonths: 4, accepts: [] }),
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-sample', 'Idempotency-Key': 'key-submit-1' },
      },
    );
    const response = await POST(request, { params: Promise.resolve({ serviceId: 's1' }) });
    expect(response.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
