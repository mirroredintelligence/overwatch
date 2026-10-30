// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { STATE_CONFIRMED } from '@/test/fixtures/bookings';
import { BACKEND_TASK_HANDLERS } from '@/test/msw/handlers/bookings';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const BACKEND = 'http://backend.test/fhir';
const TOKEN = 'token-for-advisor-one';

function session(role: Role): Session {
  return { role, services: [], sub: 'advisor-1', backendToken: TOKEN, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
}

async function get(id: string, role: Role | null = 'advisor') {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return GET(requestWithCookies(`https://app.test/api/bff/bookings/${id}`, cookies), { params: Promise.resolve({ id }) });
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  server.use(...BACKEND_TASK_HANDLERS(BACKEND));
});

describe('GET /api/bff/bookings/[id]', () => {
  it('refuses a request with no session', async () => {
    expect((await get('bk-4821', null)).status).toBe(401);
  });

  it('answers the booking state from the back end Task', async () => {
    const response = await get('bk-4821');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(STATE_CONFIRMED);
  });

  it('refuses an id that cannot be a booking, before any back-end call', async () => {
    expect((await get('x/../y')).status).toBe(400);
  });

  it('answers a booking the back end does not hold as not found', async () => {
    expect((await get('missing')).status).toBe(404);
  });
});
