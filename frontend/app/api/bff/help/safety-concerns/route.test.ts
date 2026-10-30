// @vitest-environment node
import { csrfTokenFor } from '@/lib/auth/csrf';
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
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
const backend: { body: unknown; key: string | null }[] = [];

async function post(body: unknown, role: Session['role'] = 'advisor', csrf = true) {
  const s: Session = { role, tenantId: 'trust-a', host: 'app.test', services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (csrf) headers['X-CSRF-Token'] = CSRF;
  return POST(requestWithCookies('https://app.test/api/bff/help/safety-concerns', {
    [SESSION_COOKIE]: await sealSession(s),
    diucs_csrf: CSRF,
  }, { method: 'POST', headers, body: JSON.stringify(body) }));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  backend.length = 0;
  server.use(http.post(`${EXEC_BACKEND}/Task`, (async ({ request }) => {
    backend.push({ body: await request.json(), key: request.headers.get('Idempotency-Key') });
    return HttpResponse.json({ resourceType: 'Task', identifier: [{ value: 'SC-0192' }] }, { status: 201 });
  }) as HttpResponseResolver));
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/help/safety-concerns', () => {
  it('sends a safety-concern Task with its category and text, and answers the reference only', async () => {
    const response = await post({ category: 'wrong-service-shown', text: 'Showed a closed unit' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ reference: 'SC-0192' });
    const sent = backend[0]?.body as { code: { coding: { code: string }[] }; extension: { url: string; valueCode?: string; valueString?: string }[] };
    expect(sent.code.coding[0]?.code).toBe('safety-concern');
    expect(sent.extension.find((e) => e.url.endsWith('/task-input/category'))?.valueCode).toBe('wrong-service-shown');
    expect(sent.extension.find((e) => e.url.endsWith('/task-input/text'))?.valueString).toBe('Showed a closed unit');
    expect(backend[0]?.key).toBeTruthy();
  });

  it('refuses a category the back end does not hold, with no back-end call', async () => {
    expect((await post({ category: 'nope', text: 'x' })).status).toBe(400);
    expect(backend).toHaveLength(0);
  });

  it('refuses a text of 281 characters', async () => {
    expect((await post({ category: 'something-else', text: 'x'.repeat(281) })).status).toBe(400);
    expect(backend).toHaveLength(0);
  });

  it('refuses a request with no CSRF header', async () => {
    expect((await post({ category: 'something-else', text: 'x' }, 'advisor', false)).status).toBe(403);
  });
});
