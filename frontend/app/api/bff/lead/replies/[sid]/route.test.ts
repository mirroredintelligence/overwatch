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

const URL_ = 'https://app.test/api/bff/lead/replies/SM1';
const ctx = { params: Promise.resolve({ sid: 'SM1' }) };
const KEY = 'reply-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/replies/[sid]', () => {
  it('answers 403 without the CSRF token and to an advisor', async () => {
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', key: KEY, body: { action: 'process' } }), ctx)).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY, body: { action: 'process' } }), ctx)).status).toBe(403);
  });

  it('answers 400 for an action it does not know', async () => {
    for (const action of ['delete', '__proto__', 'toString']) {
      const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { action } }), ctx);
      expect(response.status).toBe(400);
    }
  });

  it('process puts the reply on the queue through the reprocess call, with the key passed on', async () => {
    let key: string | null = null;
    server.use(
      http.post(`${BACKEND_ROOT}/admin/failed-replies/SM1/$reprocess`, ({ request }) => {
        key = request.headers.get('idempotency-key');
        return HttpResponse.json({ resolution: 'reprocessed' });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { action: 'process' } }), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ sid: 'SM1', action: 'process' });
    expect(key).toBe(KEY);
  });

  it('handled calls the handled route', async () => {
    let called = false;
    server.use(
      http.post(`${BACKEND_ROOT}/admin/failed-replies/SM1/$handled`, () => {
        called = true;
        return HttpResponse.json({ resolution: 'handled' });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { action: 'handled' } }), ctx);
    expect(response.status).toBe(200);
    expect(called).toBe(true);
  });

  it('passes a refusal of the back end on (a reply already dealt with is a 409)', async () => {
    server.use(
      http.post(`${BACKEND_ROOT}/admin/failed-replies/SM1/$handled`, () =>
        HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict' }] }, { status: 409 }),
      ),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { action: 'handled' } }), ctx);
    expect(response.status).toBe(409);
  });
});
