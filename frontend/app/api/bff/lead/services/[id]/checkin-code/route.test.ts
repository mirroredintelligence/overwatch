// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { CHECKIN_CODE } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { POST } from './route';

// Making the printed check-in code of a service through the BFF (DEC-1346).

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/lead/services/s-1/checkin-code';
const ctx = { params: Promise.resolve({ id: 's-1' }) };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/services/[id]/checkin-code', () => {
  it('answers 403 without the CSRF header and to an advisor', async () => {
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST' }), ctx)).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true }), ctx)).status).toBe(403);
  });

  it('asks the back end for the code and passes on the matrix, never cached', async () => {
    let seen = '';
    server.use(
      http.post(`${ROOT}/lead/services/s-1/checkin-code`, ({ request }) => {
        seen = new URL(request.url).pathname;
        return HttpResponse.json(CHECKIN_CODE);
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true }), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(CHECKIN_CODE);
    expect(response.headers.get('Cache-Control')).toContain('no-store');
    expect(seen).toBe('/lead/services/s-1/checkin-code');
  });

  it('passes on a 404 for a service the lead cannot see', async () => {
    server.use(http.post(`${ROOT}/lead/services/s-1/checkin-code`, () => HttpResponse.json({}, { status: 404 })));
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true }), ctx)).status).toBe(404);
  });

  it('does not pass on an answer that is not a code', async () => {
    server.use(http.post(`${ROOT}/lead/services/s-1/checkin-code`, () => HttpResponse.json({ url: 'x' })));
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true }), ctx)).status).toBeGreaterThanOrEqual(500);
  });
});
