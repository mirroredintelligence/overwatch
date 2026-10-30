// @vitest-environment node
import { csrfTokenFor } from '@/lib/auth/csrf';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { EXEC_BACKEND } from '@/test/msw/handlers/exec';
import { resetSupportBackend, seenSupport, supportBackendHandlers } from '@/test/msw/handlers/support';
import { server } from '@/test/msw/server';
import { DELETE, POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = csrfTokenFor({ tenantId: 'trust-a', host: 'app.test', sub: 'user-1' }, 'N'.repeat(43));
const SESSION = 'a1b2c3d4e5f60718';
const BODY = { sessionId: SESSION, deviceType: 'phone', appMode: 'browser', release: '0.1.0' };

async function cookies(role: Role) {
  const s: Session = { role, tenantId: 'trust-a', host: 'app.test', services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  return { [SESSION_COOKIE]: await sealSession(s), diucs_csrf: CSRF };
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetSupportBackend();
  server.use(...supportBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/support/code', () => {
  it('creates the code for this session with an Idempotency-Key, and answers the code and its end', async () => {
    const response = await POST(requestWithCookies('https://app.test/api/bff/support/code', await cookies('exec'), {
      method: 'POST',
      headers: { 'X-CSRF-Token': CSRF, 'Content-Type': 'application/json' },
      body: JSON.stringify(BODY),
    }));
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ code: 'K7R4-92QX', expiresAt: '2026-10-23T17:02:00Z' });
    const sent = seenSupport.find((s) => s.path === '/support/codes');
    expect(sent?.body).toEqual(BODY);
    expect(sent?.idempotencyKey).toBeTruthy();
  });

  it('refuses a session id that is not a session id, with no back-end call', async () => {
    const response = await POST(requestWithCookies('https://app.test/api/bff/support/code', await cookies('exec'), {
      method: 'POST',
      headers: { 'X-CSRF-Token': CSRF, 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...BODY, sessionId: 'not a session' }),
    }));
    expect(response.status).toBe(400);
    expect(seenSupport).toHaveLength(0);
  });

  it('refuses a role that may not share (support), and a request with no CSRF header', async () => {
    const refused = await POST(requestWithCookies('https://app.test/api/bff/support/code', await cookies('support'), {
      method: 'POST',
      headers: { 'X-CSRF-Token': CSRF, 'Content-Type': 'application/json' },
      body: JSON.stringify(BODY),
    }));
    expect(refused.status).toBe(403);
    const noCsrf = await POST(requestWithCookies('https://app.test/api/bff/support/code', await cookies('exec'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(BODY),
    }));
    expect(noCsrf.status).toBe(403);
    expect(seenSupport).toHaveLength(0);
  });
});

describe('DELETE /api/bff/support/code', () => {
  it('stops sharing for this session, with the CSRF header and an Idempotency-Key', async () => {
    const response = await DELETE(requestWithCookies(`https://app.test/api/bff/support/code?sessionId=${SESSION}`, await cookies('exec'), {
      method: 'DELETE',
      headers: { 'X-CSRF-Token': CSRF },
    }));
    expect(response.status).toBe(204);
    const sent = seenSupport.find((s) => s.method === 'DELETE');
    expect(sent?.path).toBe(`/support/codes/current?sessionId=${SESSION}`);
    expect(sent?.idempotencyKey).toBeTruthy();
  });
});
