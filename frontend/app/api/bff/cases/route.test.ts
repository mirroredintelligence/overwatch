// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { CSRF_COOKIE, CSRF_HEADER, csrfTokenFor } from '@/lib/auth/csrf';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = await csrfTokenFor({ tenantId: 'trust-a', host: 'app.test', sub: 'advisor-1' }, 'N'.repeat(43));
const KEY = 'idem-key-0001';
const URL_ = 'https://app.test/api/bff/cases';

const seen: { body: unknown; idempotencyKey: string | null; token: string | null }[] = [];

function session(role: Role): Session {
  return {
    role,
    tenantId: 'trust-a',
    host: 'app.test',
    services: [],
    sub: 'advisor-1',
    backendToken: 'token-for-advisor',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function post(
  role: Role | null,
  options: { csrf?: string | null; key?: string | null } = {},
): Promise<Response> {
  const cookies: Record<string, string> = { [CSRF_COOKIE]: CSRF };
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  const headers: Record<string, string> = {};
  if (options.csrf !== null) headers[CSRF_HEADER] = options.csrf ?? CSRF;
  if (options.key !== null) headers['Idempotency-Key'] = options.key ?? KEY;
  return POST(requestWithCookies(URL_, cookies, { method: 'POST', headers }));
}

beforeEach(() => {
  seen.length = 0;
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.post(`${BACKEND_BASE}/ServiceRequest`, async ({ request }) => {
      seen.push({
        body: await request.clone().json(),
        idempotencyKey: request.headers.get('idempotency-key'),
        token: request.headers.get('authorization'),
      });
      return HttpResponse.json({ resourceType: 'ServiceRequest', id: '4821' }, { status: 201 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('POST /api/bff/cases (W10)', () => {
  it('answers 403 for a reporter and opens no case at the back end', async () => {
    const response = await post('reporter');

    expect(response.status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('opens an empty case for an advisor and answers only the id', async () => {
    const response = await post('advisor');

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ id: '4821' });
    expect(seen).toHaveLength(1);
    expect(seen[0].body).toEqual({ resourceType: 'ServiceRequest' });
    expect(seen[0].idempotencyKey).toBe(KEY);
    expect(seen[0].token).toBe('Bearer token-for-advisor');
  });

  it('refuses a shift lead, the page guard and the back end agreeing that a lead does not work a call (DEC-860)', async () => {
    expect((await post('lead')).status).toBe(403);
    expect((await post('clinical')).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('refuses a request with no CSRF header', async () => {
    const response = await post('advisor', { csrf: null });

    expect(response.status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('refuses a missing or malformed Idempotency-Key', async () => {
    expect((await post('advisor', { key: null })).status).toBe(400);
    expect((await post('advisor', { key: 'short' })).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('is never cached', async () => {
    expect((await post('advisor')).headers.get('cache-control')).toBe('private, no-store');
  });
});
