// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { EXEC_BACKEND } from '@/test/msw/handlers/exec';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});


async function get(role: Role, id: string) {
  const s: Session = { role, services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  return GET(requestWithCookies(`https://app.test/api/bff/exec/services/${id}`, { [SESSION_COOKIE]: await sealSession(s) }), { params: Promise.resolve({ id }) });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/exec/services/[id]', () => {
  it('answers the service from the board the caller can read', async () => {
    const response = await get('exec', 'svc-ucr-west');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(expect.objectContaining({ serviceId: 'svc-ucr-west', name: 'UCR West' }));
  });

  it('answers 404 for a service that is not on the board', async () => {
    expect((await get('exec', 'svc-not-here')).status).toBe(404);
  });

  it('refuses a role that is not an executive or a shift lead', async () => {
    expect((await get('advisor', 'svc-ucr-west')).status).toBe(403);
  });
});
