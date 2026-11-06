// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET, POST } from './route';

// The duty roster of one service through the BFF (DEC-1341).

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/lead/services/s-virtual-ward/roster';
const ctx = { params: Promise.resolve({ id: 's-virtual-ward' }) };
const KEY = 'roster-key-0001';

const ANSWER = {
  managers: [{ roleId: 'role-1', name: 'Ana Duty', numberEnding: '0111', state: 'off-shift', shiftEnd: null }],
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/services/[id]/roster', () => {
  it('answers 403 to an advisor and 401 with no session', async () => {
    expect((await GET(await leadRequest(URL_, 'advisor'), ctx)).status).toBe(403);
    expect((await GET(await leadRequest(URL_, null), ctx)).status).toBe(401);
  });

  it('reads the roster from the back end root for a lead and passes it on, checked', async () => {
    server.use(http.get(`${ROOT}/lead/services/s-virtual-ward/roster`, () => HttpResponse.json(ANSWER)));
    const response = await GET(await leadRequest(URL_, 'lead'), ctx);
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    expect(await response.json()).toEqual(ANSWER);
  });

  it('is an error, not an empty roster, when the answer is not the shape the page knows', async () => {
    server.use(http.get(`${ROOT}/lead/services/s-virtual-ward/roster`, () => HttpResponse.json({ managers: 'no' })));
    expect((await GET(await leadRequest(URL_, 'lead'), ctx)).status).toBeGreaterThanOrEqual(500);
  });
});

describe('POST /api/bff/lead/services/[id]/roster', () => {
  const body = { name: 'Ben Duty', mobile: '07700 900222' };

  it('answers 403 without the CSRF header and to an advisor', async () => {
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', key: KEY, body }), ctx)).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY, body }), ctx)).status).toBe(403);
  });

  it('answers 400 with no Idempotency-Key, a short name or a number that is not a UK mobile, and calls nothing', async () => {
    let called = false;
    server.use(http.post(`${ROOT}/lead/services/s-virtual-ward/roster`, () => { called = true; return HttpResponse.json({}, { status: 201 }); }));
    for (const request of [
      await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, body }),
      await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { ...body, name: 'B' } }),
      await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { ...body, mobile: '12345' } }),
    ]) {
      expect((await POST(request, ctx)).status).toBe(400);
    }
    expect(called).toBe(false);
  });

  it('sends the person to the back end with the key and answers the new place only', async () => {
    let seen: { key: string | null; body: unknown } | undefined;
    server.use(
      http.post(`${ROOT}/lead/services/s-virtual-ward/roster`, async ({ request }) => {
        seen = { key: request.headers.get('idempotency-key'), body: await request.json() };
        return HttpResponse.json({ roleId: 'role-new' }, { status: 201 });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body }), ctx);
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ roleId: 'role-new' });
    expect(seen).toEqual({ key: KEY, body });
  });

  it('passes on a 409 when the person is already on the roster', async () => {
    server.use(http.post(`${ROOT}/lead/services/s-virtual-ward/roster`, () => HttpResponse.json({}, { status: 409 })));
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body }), ctx);
    expect(response.status).toBe(409);
  });
});
