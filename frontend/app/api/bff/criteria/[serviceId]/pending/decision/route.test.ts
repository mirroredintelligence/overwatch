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

const lead = () =>
  sealSession({
    role: 'lead',
    services: [],
    sub: 'sample-sub',
    backendToken: 'sample-token',
    expiresAt: new Date(Date.now() + 3600_000).toISOString(),
  });

describe('POST /api/bff/criteria/[serviceId]/pending/decision', () => {
  it('refuses a decision other than approve or send-back, with 400 and no upstream call', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const cookie = await lead();
    const request = requestWithCookies(
      'https://app.test/api/bff/criteria/s1/pending/decision',
      { diucs_session: cookie, diucs_csrf: 'csrf-sample' },
      {
        method: 'POST',
        body: JSON.stringify({ decision: 'maybe' }),
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-sample', 'Idempotency-Key': 'key-approve-1' },
      },
    );
    const response = await POST(request, { params: Promise.resolve({ serviceId: 's1' }) });
    expect(response.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
