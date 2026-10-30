// @vitest-environment node
import { csrfTokenFor } from '@/lib/auth/csrf';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { clinicalBackendHandlers, resetClinicalBackend, seenClinical } from '@/test/msw/handlers/clinical';
import { EXEC_BACKEND } from '@/test/msw/handlers/exec';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = csrfTokenFor({ tenantId: 'trust-a', host: 'app.test', sub: 'user-1' }, 'N'.repeat(43));

async function advise(body: unknown) {
  const s: Session = { role: 'clinical', tenantId: 'trust-a', host: 'app.test', services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  const request = requestWithCookies(`https://app.test/api/bff/clinical/requests/req-4821/advice`, {
    [SESSION_COOKIE]: await sealSession(s),
    diucs_csrf: CSRF,
  }, { method: 'POST', headers: { 'X-CSRF-Token': CSRF, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return POST(request, { params: Promise.resolve({ id: 'req-4821' }) });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetClinicalBackend();
  server.use(...clinicalBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/clinical/requests/[id]/advice', () => {
  it('sends the advice as the back end\'s Parameters, with the note kept out of any log', async () => {
    const response = await advise({ advice: 'go-ahead', reason: 'within-criteria-on-judgement', note: 'Checked with the referrer' });
    expect(response.status).toBe(200);
    const sent = seenClinical.find((c) => c.path === '/Task/req-4821/$advise');
    expect(sent?.body).toEqual({
      resourceType: 'Parameters',
      parameter: [
        { name: 'advice', valueCode: 'go-ahead' },
        { name: 'reason', valueCode: 'within-criteria-on-judgement' },
        { name: 'note', valueString: 'Checked with the referrer' },
      ],
    });
    expect(sent?.idempotencyKey).toBeTruthy();
  });

  it('refuses an advice choice the back end does not offer, with no back-end call', async () => {
    expect((await advise({ advice: 'maybe' })).status).toBe(400);
    expect(seenClinical.filter((c) => c.path.endsWith('$advise'))).toHaveLength(0);
  });

  it('refuses a note of 281 characters', async () => {
    expect((await advise({ advice: 'go-ahead', note: 'x'.repeat(281) })).status).toBe(400);
  });
});
