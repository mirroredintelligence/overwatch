// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { clinicalBackendHandlers, resetClinicalBackend, TAKEN_ELSEWHERE } from '@/test/msw/handlers/clinical';
import { EXEC_BACKEND } from '@/test/msw/handlers/exec';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const CSRF = 'csrf-token-for-the-test';

async function take(id: string) {
  const s: Session = { role: 'clinical', services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  const request = requestWithCookies(`https://app.test/api/bff/clinical/requests/${id}/take`, {
    [SESSION_COOKIE]: await sealSession(s),
    diucs_csrf: CSRF,
  }, { method: 'POST', headers: { 'X-CSRF-Token': CSRF } });
  return POST(request, { params: Promise.resolve({ id }) });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetClinicalBackend();
  server.use(...clinicalBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/clinical/requests/[id]/take', () => {
  it('takes the request with an Idempotency-Key', async () => {
    const response = await take('req-4821');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ id: 'req-4821', status: 'in-progress' });
  });

  it('answers 409 when another clinician has taken it, with no detail of who', async () => {
    const response = await take(TAKEN_ELSEWHERE);
    expect(response.status).toBe(409);
    expect(JSON.stringify(await response.json())).not.toMatch(/practitioner|clinician-/i);
  });
});
