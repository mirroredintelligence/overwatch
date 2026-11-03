// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { BACKEND_ROOT } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

// The download request (DEC-1329), lead only: the back end queues the district and answers 202; nothing is
// downloaded in this request.

const URL_ = 'https://app.test/api/bff/postcode-districts/download';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/postcode-districts/download', () => {
  it('asks the back end to queue the district and answers 202 with the queued status', async () => {
    let asked: string | null = null;
    server.use(
      http.post(`${BACKEND_ROOT}/postcode-districts/download`, ({ request }) => {
        asked = new URL(request.url).searchParams.get('text');
        return HttpResponse.json({ prefix: 'DT4', status: 'queued' }, { status: 202 });
      }),
    );
    const response = await POST(
      await leadRequest(`${URL_}?text=DT4`, 'lead', { method: 'POST', csrf: true, body: {} }),
    );
    expect(response.status).toBe(202);
    expect(asked).toBe('DT4');
    expect(await response.json()).toEqual({ prefix: 'DT4', status: 'queued' });
  });

  it('refuses a request with no csrf token, without calling the back end', async () => {
    let called = false;
    server.use(
      http.post(`${BACKEND_ROOT}/postcode-districts/download`, () => {
        called = true;
        return HttpResponse.json({}, { status: 202 });
      }),
    );
    const response = await POST(await leadRequest(`${URL_}?text=DT4`, 'lead', { method: 'POST', body: {} }));
    expect(response.status).toBe(403);
    expect(called).toBe(false);
  });
});
