// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { CASE_REF, SERVICE_ID, STATE_REQUESTED } from '@/test/fixtures/bookings';
import { server } from '@/test/msw/server';
import { BACKEND_TASK_HANDLERS } from '@/test/msw/handlers/bookings';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const BACKEND = 'http://backend.test/fhir';
const URL_ = 'https://app.test/api/bff/bookings';
const KEY = '9f1c2b3a-4d5e-4f60-8a7b-1c2d3e4f5a6b';
const TOKEN = 'token-for-advisor-one';

function session(role: Role): Session {
  return {
    role,
    services: [],
    sub: 'advisor-1',
    backendToken: TOKEN,
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

type Options = { role?: Role | null; key?: string | null; csrf?: string | null; body?: unknown; raw?: string };

async function post(options: Options = {}) {
  const role = options.role === undefined ? 'advisor' : options.role;
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  const csrf = options.csrf === undefined ? 'csrf-value' : options.csrf;
  if (csrf !== null) cookies[CSRF_COOKIE] = csrf;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (options.key !== null) headers['Idempotency-Key'] = options.key ?? KEY;
  if (csrf !== null) headers[CSRF_HEADER] = csrf;
  const body = options.raw ?? JSON.stringify(options.body ?? { caseRef: CASE_REF, serviceId: SERVICE_ID });
  return POST(requestWithCookies(URL_, cookies, { method: 'POST', headers, body }));
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  server.use(...BACKEND_TASK_HANDLERS(BACKEND));
});

describe('POST /api/bff/bookings', () => {
  it('refuses a request with no session', async () => {
    expect((await post({ role: null })).status).toBe(401);
  });

  it('refuses a role that may not request a booking', async () => {
    expect((await post({ role: 'reporter' })).status).toBe(403);
  });

  it('refuses a request with no CSRF header', async () => {
    expect((await post({ csrf: null })).status).toBe(403);
  });

  it('refuses a request with no Idempotency-Key, before the back end is called', async () => {
    const response = await post({ key: null });
    expect(response.status).toBe(400);
  });

  it('refuses any field that is not caseRef or serviceId, such as a tenant', async () => {
    const response = await post({ body: { caseRef: CASE_REF, serviceId: SERVICE_ID, tenantId: 'tenant-b' } });
    expect(response.status).toBe(400);
    expect(JSON.stringify(await response.json())).not.toContain('tenant-b');
  });

  it('opens the request at the back end with the session token and the key, and answers the booking state', async () => {
    const response = await post();
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual(STATE_REQUESTED);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
  });

  it('answers 409 open-request when the service already has a request waiting', async () => {
    const response = await post({ body: { caseRef: CASE_REF, serviceId: 'ucr-busy' } });
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ code: 'open-request' });
  });
});
