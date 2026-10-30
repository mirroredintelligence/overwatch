// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { GET } from './route';

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

describe('GET /api/bff/registrations', () => {
  it('answers 401 without a lead session, and calls nothing upstream', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const response = await GET(new Request('https://app.test/api/bff/registrations?tab=to-review'));
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ code: 'no-session' });
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('answers 403 to a signed-in role that is not lead, and calls nothing upstream', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const { sealSession } = await import('@/lib/auth/session');
    const cookie = await sealSession({
      role: 'advisor',
      services: [],
      sub: 'sample-sub',
      backendToken: 'sample-token',
      expiresAt: new Date(Date.now() + 3600_000).toISOString(),
    });
    const response = await GET(requestWithCookies('https://app.test/api/bff/registrations?tab=to-review', { diucs_session: cookie }));
    expect(response.status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
