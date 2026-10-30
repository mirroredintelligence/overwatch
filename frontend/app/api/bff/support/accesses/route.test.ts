// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { EXEC_BACKEND } from '@/test/msw/handlers/exec';
import { resetSupportBackend, seenSupport, supportBackendHandlers } from '@/test/msw/handlers/support';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const SESSION = 'a1b2c3d4e5f60718';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetSupportBackend();
  server.use(...supportBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

async function get(query: string) {
  const s: Session = { role: 'exec', services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  return GET(requestWithCookies(`https://app.test/api/bff/support/accesses${query}`, { [SESSION_COOKIE]: await sealSession(s) }));
}

describe('GET /api/bff/support/accesses', () => {
  it('lists when the session was opened and by whom, as role only', async () => {
    const response = await get(`?sessionId=${SESSION}`);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([{ openedAt: '2026-10-23T13:02:00Z', role: 'support' }]);
  });

  it('refuses a session id that is not one, with no back-end call', async () => {
    expect((await get('?sessionId=../../x')).status).toBe(400);
    expect(seenSupport).toHaveLength(0);
  });
});
