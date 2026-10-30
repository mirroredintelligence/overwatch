// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { clinicalBackendHandlers, resetClinicalBackend } from '@/test/msw/handlers/clinical';
import { EXEC_BACKEND } from '@/test/msw/handlers/exec';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetClinicalBackend();
  server.use(...clinicalBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/clinical/summary', () => {
  it('answers the waiting count and the number of advisors available, as counts only', async () => {
    const s: Session = { role: 'clinical', tenantId: 'trust-a', host: 'app.test', services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
    const response = await GET(requestWithCookies('https://app.test/api/bff/clinical/summary', { [SESSION_COOKIE]: await sealSession(s) }));
    expect(await response.json()).toEqual({ waiting: 2, available: 2 });
  });
});
