// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const CSRF = 'csrf-token-for-the-test';

async function post(body: unknown) {
  const s: Session = { role: 'exec', services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  return POST(requestWithCookies('https://app.test/api/bff/help/problems', {
    [SESSION_COOKIE]: await sealSession(s),
    diucs_csrf: CSRF,
  }, { method: 'POST', headers: { 'X-CSRF-Token': CSRF, 'Content-Type': 'application/json' }, body: JSON.stringify(body) }));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', 'http://backend.test/fhir');
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/help/problems', () => {
  it('answers unavailable: the back end has no route for a problem report yet, and nothing is kept', async () => {
    const response = await post({ kind: 'button-does-not-work', route: '/case/[ref]' });
    expect(response.status).toBe(503);
  });

  it('refuses a kind the back end does not hold, with 400', async () => {
    expect((await post({ kind: 'button-not-working', route: '/help' })).status).toBe(400);
  });

  it('refuses a route that is not a page path, with 400', async () => {
    expect((await post({ kind: 'screen-slow', route: 'https://elsewhere.example/x' })).status).toBe(400);
  });
});
