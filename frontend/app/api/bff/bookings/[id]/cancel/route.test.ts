// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER, csrfTokenFor } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_TASK_HANDLERS } from '@/test/msw/handlers/bookings';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const BACKEND = 'http://backend.test/fhir';
const KEY = '5b7e9c1d-2a3f-4b5c-8d9e-0f1a2b3c4d5e';
const TOKEN = 'token-for-advisor-one';
// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF_VALUE = csrfTokenFor({ tenantId: 'trust-a', host: 'app.test', sub: 'advisor-1' }, 'N'.repeat(43));

function session(role: Role): Session {
  return { role, tenantId: 'trust-a', host: 'app.test', services: [], sub: 'advisor-1', backendToken: TOKEN, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
}

type Options = { id?: string; role?: Role | null; key?: string | null; csrf?: string | null; body?: unknown };

async function post(options: Options = {}) {
  const role = options.role === undefined ? 'advisor' : options.role;
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  const csrf = options.csrf === undefined ? CSRF_VALUE : options.csrf;
  if (csrf !== null) cookies[CSRF_COOKIE] = csrf;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (options.key !== null) headers['Idempotency-Key'] = options.key ?? KEY;
  if (csrf !== null) headers[CSRF_HEADER] = csrf;
  const url = `https://app.test/api/bff/bookings/${options.id ?? 'bk-4821'}/cancel`;
  return POST(requestWithCookies(url, cookies, { method: 'POST', headers, body: JSON.stringify(options.body ?? { reason: 'no-longer-needed' }) }), {
    params: Promise.resolve({ id: options.id ?? 'bk-4821' }),
  });
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  server.use(...BACKEND_TASK_HANDLERS(BACKEND));
});

describe('POST /api/bff/bookings/[id]/cancel', () => {
  it('refuses no session, and a role that may not cancel', async () => {
    expect((await post({ role: null })).status).toBe(401);
    expect((await post({ role: 'reporter' })).status).toBe(403);
  });

  it('refuses a request with no CSRF header, or no Idempotency-Key', async () => {
    expect((await post({ csrf: null })).status).toBe(403);
    expect((await post({ key: null })).status).toBe(400);
  });

  it('refuses a reason that is not one of the four, and any other field', async () => {
    expect((await post({ body: { reason: 'because' } })).status).toBe(400);
    expect((await post({ body: { reason: 'entered-in-error', tenantId: 'tenant-b' } })).status).toBe(400);
  });

  it('cancels at the back end and answers the status the booking now has', async () => {
    const response = await post();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'cancelled-before' });
  });

  it('answers 409 state-changed with the status the booking now has, when it moved on', async () => {
    const response = await post({ id: 'taken' });
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ code: 'state-changed', status: 'confirmed' });
  });
});
