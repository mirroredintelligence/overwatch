// @vitest-environment node
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { cookiesMock, requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// Submit for approval (W26): the back end's $submit (R10), with the reporter's token and an
// idempotency key. Its refusal comes back as the errors the review shows.

const ID = 'REG-SAMPLE-1';
const CSRF = 'csrf-sample-token';
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}/submit`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });
let upstream: { auth: string | null; idem: string | null; path: string } | null = null;

async function sessionFor(role: Session['role']): Promise<string> {
  return sealSession({ role, services: [], sub: 'person-sample-1', backendToken: 'backend-token-sample-value', expiresAt: new Date(Date.now() + 3_600_000).toISOString() });
}

function answerWith(status: number, body: unknown) {
  server.use(
    http.post(`${BACKEND_ROOT}/fhir/Task/${ID}/$submit`, (({ request }) => {
      upstream = { auth: request.headers.get('authorization'), idem: request.headers.get('idempotency-key'), path: new URL(request.url).pathname };
      return HttpResponse.json(body as Record<string, unknown>, { status });
    }) as HttpResponseResolver),
  );
}

function post(role: Session['role'] = 'reporter', csrf: string | null = CSRF) {
  const headers: Record<string, string> = {};
  if (csrf !== null) headers[CSRF_HEADER] = csrf;
  return requestWithCookies(url, { [SESSION_COOKIE]: 'x', [CSRF_COOKIE]: CSRF }, { method: 'POST', headers });
}

beforeEach(async () => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  cookiesMock.mockClear();
  upstream = null;
  answerWith(200, { resourceType: 'Task', id: ID, businessStatus: { coding: [{ system: 'x', code: 'submitted' }] } });
});

async function call(role: Session['role'] = 'reporter', csrf: string | null = CSRF) {
  const request = post(role, csrf);
  const headers = new Headers(request.headers);
  headers.set('Cookie', `${SESSION_COOKIE}=${await sessionFor(role)}; ${CSRF_COOKIE}=${CSRF}`);
  return POST(new Request(request.url, { method: 'POST', headers }), ctx(ID));
}

describe('POST /api/bff/registrations/[id]/submit', () => {
  it('submits with the reporter’s token and an idempotency key, and answers the new status', async () => {
    const response = await call();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'submitted' });
    expect(upstream).toMatchObject({ path: `/fhir/Task/${ID}/$submit`, auth: 'Bearer backend-token-sample-value' });
    expect(upstream?.idem).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('refuses a submit with no CSRF header (403), another role (403), and writes nothing upstream', async () => {
    expect((await call('reporter', null)).status).toBe(403);
    expect((await call('advisor')).status).toBe(403);
    expect(upstream).toBeNull();
  });

  it('answers the back end’s refusal as 422 with the errors on the fields it names', async () => {
    answerWith(400, {
      resourceType: 'OperationOutcome',
      issue: [{ severity: 'error', code: 'invalid', diagnostics: 'Enter the API address, starting https://', expression: ['address'] }],
    });
    const response = await call();
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({ errors: [{ field: 'address', message: 'Enter the API address, starting https://' }] });
  });
});
