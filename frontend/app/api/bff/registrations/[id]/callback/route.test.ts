// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { sealSession } from '@/lib/auth/session';
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

const body = (value: unknown) => JSON.stringify(value);

describe('POST /api/bff/registrations/[id]/callback', () => {
  it('refuses a write with no CSRF header, and calls nothing upstream', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const cookie = await lead();
    const request = requestWithCookies(
      'https://app.test/api/bff/registrations/r1/callback',
      { diucs_session: cookie },
      { method: 'POST', body: body({ result: 'no-answer', numberCalled: '01202 000 111' }), headers: { 'Content-Type': 'application/json' } },
    );
    const response = await POST(request, { params: Promise.resolve({ id: 'r1' }) });
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ code: 'csrf' });
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('refuses a result the back end does not know, with 400 and no upstream call', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const cookie = await lead();
    const request = requestWithCookies(
      'https://app.test/api/bff/registrations/r1/callback',
      { diucs_session: cookie, diucs_csrf: 'csrf-sample' },
      {
        method: 'POST',
        body: body({ result: 'maybe', numberCalled: '01202 000 111' }),
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-sample', 'Idempotency-Key': 'key-cb-1' },
      },
    );
    const response = await POST(request, { params: Promise.resolve({ id: 'r1' }) });
    expect(response.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
