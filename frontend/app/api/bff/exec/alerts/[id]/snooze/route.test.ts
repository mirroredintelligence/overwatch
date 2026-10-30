// @vitest-environment node
import { csrfTokenFor } from '@/lib/auth/csrf';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { EXEC_BACKEND, execBackendHandlers, resetExecBackend } from '@/test/msw/handlers/exec';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = csrfTokenFor({ tenantId: 'trust-a', host: 'app.test', sub: 'user-1' }, 'N'.repeat(43));

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetExecBackend();
  server.use(...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/exec/alerts/[id]/snooze', () => {
  it('moves the escalation on by an hour and answers the new due time', async () => {
    const s: Session = { role: 'exec', tenantId: 'trust-a', host: 'app.test', services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
    const request = requestWithCookies('https://app.test/api/bff/exec/alerts/al-1/snooze', {
      [SESSION_COOKIE]: await sealSession(s),
      diucs_csrf: CSRF,
    }, { method: 'POST', headers: { 'X-CSRF-Token': CSRF } });
    const response = await POST(request, { params: Promise.resolve({ id: 'al-1' }) });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ alertId: 'al-1', escalatesAt: '2026-10-23T14:19:00Z' });
  });
});
