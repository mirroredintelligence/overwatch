// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/lead/services/s-ucr-east/phoned';
const ctx = { params: Promise.resolve({ id: 's-ucr-east' }) };
const KEY = 'lead-phoned-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/services/[id]/phoned', () => {
  it('answers 403 to an advisor (the advisor records on a case), and 403 with no CSRF header', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY, body: { said: 'accepting', value: 2 } }), ctx)).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', key: KEY, body: { said: 'accepting', value: 2 } }), ctx)).status).toBe(403);
  });

  it('refuses an answer the service can not give, a case reference, and no key, and calls nothing', async () => {
    let called = false;
    server.use(http.post(`${ROOT}/lead/services/s-ucr-east/phoned`, () => { called = true; return HttpResponse.json({}); }));
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { said: 'maybe', value: 2 } }), ctx)).status).toBe(400);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { said: 'accepting' } }), ctx)).status).toBe(400);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { said: 'accepting', value: 2, caseRef: 'c-1' } }), ctx)).status).toBe(400);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, body: { said: 'accepting', value: 2 } }), ctx)).status).toBe(400);
    expect(called).toBe(false);
  });

  it('records what the service said with the key, a not-accepting answer as 0, and answers recorded', async () => {
    const sent: { body: unknown; key: string | null }[] = [];
    server.use(
      http.post(`${ROOT}/lead/services/s-ucr-east/phoned`, async ({ request }) => {
        sent.push({ body: await request.json(), key: request.headers.get('idempotency-key') });
        return HttpResponse.json({ reportId: 'r-9', value: 0 }, { status: 201 });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { said: 'not-accepting' } }), ctx);
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ recorded: true, value: 0 });
    expect(sent).toEqual([{ body: { told: 'not-accepting' }, key: KEY }]);
  });

  it('sends a figure for accepting and limited answers', async () => {
    let body: unknown;
    server.use(
      http.post(`${ROOT}/lead/services/s-ucr-east/phoned`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ reportId: 'r-10', value: 3 }, { status: 201 });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { said: 'limited', value: 3 } }), ctx);
    expect(response.status).toBe(201);
    expect(body).toEqual({ told: 'limited', value: 3 });
  });
});
