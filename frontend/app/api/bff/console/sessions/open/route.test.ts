// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER, csrfTokenFor } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const BACKEND_ROOT = 'http://backend.test';
const URL_ = 'https://app.test/api/bff/console/sessions/open';
// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = csrfTokenFor({ tenantId: 'trust-a', host: 'app.test', sub: 'user-1' }, 'N'.repeat(43));

function session(role: Role): Session {
  return {
    role,
    tenantId: 'trust-a',
    host: 'app.test',
    services: [],
    sub: 'user-1',
    backendToken: 'token-for-the-support-user',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function post(role: Role | null, body: unknown) {
  const cookies: Record<string, string> = { [CSRF_COOKIE]: CSRF };
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return POST(
    requestWithCookies(URL_, cookies, {
      method: 'POST',
      headers: { 'content-type': 'application/json', [CSRF_HEADER]: CSRF },
      body: JSON.stringify(body),
    }),
  );
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('POST /api/bff/console/sessions/open', () => {
  it('opens the session at the back end root with a fresh idempotency key and answers its id', async () => {
    const seen: { path: string; key: string | null; body: unknown } = { path: '', key: null, body: null };
    server.use(
      http.post(`${BACKEND_ROOT}/support/sessions/open`, async ({ request }) => {
        seen.path = new URL(request.url).pathname;
        seen.key = request.headers.get('idempotency-key');
        seen.body = await request.json();
        return HttpResponse.json({ sessionId: 's-7f3a9c2e1b', expiresAt: '2026-10-30T14:30:00Z' });
      }),
    );

    const response = await post('support', { supportCode: 'ABC123' });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ sessionId: 's-7f3a9c2e1b', expiresAt: '2026-10-30T14:30:00Z' });
    expect(seen.path).toBe('/support/sessions/open');
    expect(seen.key).toMatch(/^[\x21-\x7e]{1,200}$/);
    expect(seen.body).toEqual({ supportCode: 'ABC123' });
  });

  it('refuses a session whose role is not support, before the back end is called', async () => {
    let called = false;
    server.use(
      http.post(`${BACKEND_ROOT}/support/sessions/open`, () => {
        called = true;
        return HttpResponse.json({});
      }),
    );

    const response = await post('advisor', { supportCode: 'ABC123' });

    expect(response.status).toBe(403);
    expect(called).toBe(false);
  });

  it('answers 401 with no session', async () => {
    const response = await post(null, { supportCode: 'ABC123' });

    expect(response.status).toBe(401);
  });

  it('refuses a body that gives both a code and a ticket, or neither', async () => {
    expect((await post('support', { supportCode: 'ABC123', ticket: 'T-1' })).status).toBe(400);
    expect((await post('support', {})).status).toBe(400);
  });

  it('refuses a request that names a tenant with 400, and calls nothing (TEN-044)', async () => {
    const seen: { body: unknown } = { body: null };
    server.use(
      http.post(`${BACKEND_ROOT}/support/sessions/open`, async ({ request }) => {
        seen.body = await request.json();
        return HttpResponse.json({ sessionId: 's-7f3a9c2e1b', expiresAt: '2026-10-30T14:30:00Z' });
      }),
    );

    const response = await post('support' as Role, { supportCode: 'ABC123', tenantId: 'tenant-b' });

    expect(response.status).toBe(400);
    expect(seen.body).toBeNull();
  });

  it('forwards the support code alone', async () => {
    const seen: { body: unknown } = { body: null };
    server.use(
      http.post(`${BACKEND_ROOT}/support/sessions/open`, async ({ request }) => {
        seen.body = await request.json();
        return HttpResponse.json({ sessionId: 's-7f3a9c2e1b', expiresAt: '2026-10-30T14:30:00Z' });
      }),
    );

    await post('support' as Role, { supportCode: 'ABC123', note: 'extra' });

    expect(seen.body).toEqual({ supportCode: 'ABC123' });
  });
});
