// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_TASK_HANDLERS } from '@/test/msw/handlers/bookings';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const BACKEND = 'http://backend.test/fhir';
const KEY = '7c1d2e3f-4a5b-4c6d-9e0f-1a2b3c4d5e6f';
const TOKEN = 'token-for-advisor-one';

function session(role: Role): Session {
  return { role, services: [], sub: 'advisor-1', backendToken: TOKEN, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
}

async function post(role: Role | null = 'advisor', key: string | null = KEY) {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  cookies[CSRF_COOKIE] = 'csrf-value';
  const headers: Record<string, string> = { 'Content-Type': 'application/json', [CSRF_HEADER]: 'csrf-value' };
  if (key !== null) headers['Idempotency-Key'] = key;
  return POST(requestWithCookies('https://app.test/api/bff/bookings/bk-4821/acknowledge', cookies, { method: 'POST', headers, body: '{}' }), {
    params: Promise.resolve({ id: 'bk-4821' }),
  });
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  server.use(...BACKEND_TASK_HANDLERS(BACKEND));
});

describe('POST /api/bff/bookings/[id]/acknowledge', () => {
  it('refuses no session, a role that may not acknowledge, and no Idempotency-Key', async () => {
    expect((await post(null)).status).toBe(401);
    expect((await post('reporter')).status).toBe(403);
    expect((await post('advisor', null)).status).toBe(400);
  });

  it('acknowledges at the back end and answers acknowledged true', async () => {
    const response = await post();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ acknowledged: true });
  });
});
