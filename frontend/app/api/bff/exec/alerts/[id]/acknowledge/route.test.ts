// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { EXEC_BACKEND, execBackendHandlers, resetExecBackend, seenBackend } from '@/test/msw/handlers/exec';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const CSRF = 'csrf-token-for-the-test';

async function post(role: Role, id: string, withCsrf = true) {
  const s: Session = { role, services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  const headers: Record<string, string> = {};
  if (withCsrf) headers['X-CSRF-Token'] = CSRF;
  const request = requestWithCookies(`https://app.test/api/bff/exec/alerts/${id}/acknowledge`, {
    [SESSION_COOKIE]: await sealSession(s),
    diucs_csrf: CSRF,
  }, { method: 'POST', headers });
  return POST(request, { params: Promise.resolve({ id }) });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetExecBackend();
  server.use(...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/exec/alerts/[id]/acknowledge', () => {
  it('acknowledges the alert with an Idempotency-Key and returns its new status', async () => {
    const response = await post('exec', 'al-1');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ id: 'al-1', status: 'acknowledged' });
    const call = seenBackend.find((r) => r.path === '/Task/al-1/$acknowledge');
    expect(call?.idempotencyKey).toBeTruthy();
  });

  it('refuses a request with no CSRF header before it calls the back end', async () => {
    expect((await post('exec', 'al-1', false)).status).toBe(403);
    expect(seenBackend).toHaveLength(0);
  });

  it('refuses an id that is not a plausible alert id', async () => {
    expect((await post('exec', '../etc')).status).toBe(404);
  });
});
