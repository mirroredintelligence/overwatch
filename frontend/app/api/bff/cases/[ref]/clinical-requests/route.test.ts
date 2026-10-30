// @vitest-environment node
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { requestBodies } from '@/test/msw/handlers/clinical';
import { EXEC_BACKEND } from '@/test/msw/handlers/exec';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const CSRF = 'csrf-token-for-the-test';

async function post(body: unknown, role: Session['role'] = 'advisor') {
  const s: Session = { role, services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  return POST(requestWithCookies('https://app.test/api/bff/cases/case-4821/clinical-requests', {
    [SESSION_COOKIE]: await sealSession(s),
    diucs_csrf: CSRF,
  }, { method: 'POST', headers: { 'X-CSRF-Token': CSRF, 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), { params: Promise.resolve({ ref: 'case-4821' }) });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  requestBodies.length = 0;
  server.use(http.post(`${EXEC_BACKEND}/Task`, (async ({ request }) => {
    requestBodies.push(await request.json());
    return HttpResponse.json({ resourceType: 'Task', id: 'req-9001', businessStatus: { coding: [{ code: 'requested' }] } }, { status: 201 });
  }) as HttpResponseResolver));
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/cases/[ref]/clinical-requests', () => {
  it('asks for clinical advice on the case, with urgency and reason as the back end takes them', async () => {
    const response = await post({ urgency: 'now', why: 'borderline-criteria' });
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ requestId: 'req-9001' });
    const sent = requestBodies[0] as { focus: { reference: string }; code: { coding: { code: string }[] }; extension: { url: string; valueCode: string }[] };
    expect(sent.code.coding[0]?.code).toBe('clinical-advice');
    expect(sent.focus.reference).toBe('ServiceRequest/case-4821');
    expect(sent.extension.find((e) => e.url.endsWith('/task-input/urgency'))?.valueCode).toBe('now');
    expect(sent.extension.find((e) => e.url.endsWith('/task-input/why'))?.valueCode).toBe('borderline-criteria');
  });

  it('refuses an urgency the back end does not take, and a missing reason, with no back-end call', async () => {
    expect((await post({ urgency: 'soon', why: 'other' })).status).toBe(400);
    expect((await post({ urgency: 'now' })).status).toBe(400);
    expect(requestBodies).toHaveLength(0);
  });

  it('refuses a role that is not an advisor, a clinical advisor or a lead', async () => {
    expect((await post({ urgency: 'now', why: 'other' }, 'exec')).status).toBe(403);
  });
});
