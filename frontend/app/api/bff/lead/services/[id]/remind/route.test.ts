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
const URL_ = 'https://app.test/api/bff/lead/services/s-virtual-ward/remind';
const ctx = { params: Promise.resolve({ id: 's-virtual-ward' }) };
const KEY = 'remind-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/services/[id]/remind', () => {
  it('answers 403 without the CSRF header, even for a lead', async () => {
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', key: KEY }), ctx);
    expect(response.status).toBe(403);
    expect(((await response.json()) as { code: string }).code).toBe('csrf');
  });

  it('answers 403 to an advisor even with the CSRF header', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY }), ctx)).status).toBe(403);
  });

  it('answers 400 with no Idempotency-Key, and does not call the back end', async () => {
    let called = false;
    server.use(http.post(`${ROOT}/lead/services/s-virtual-ward/remind`, () => { called = true; return HttpResponse.json({}); }));
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true }), ctx);
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('sends the reminder to the back end with the key, and answers that it was sent', async () => {
    let key: string | null = null;
    server.use(
      http.post(`${ROOT}/lead/services/s-virtual-ward/remind`, ({ request }) => {
        key = request.headers.get('idempotency-key');
        return HttpResponse.json({ reminded: true });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY }), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ reminded: true });
    expect(key).toBe(KEY);
  });

  it('answers 409 when no reminder is waiting for the service, and says nothing of the number', async () => {
    server.use(
      http.post(`${ROOT}/lead/services/s-virtual-ward/remind`, () =>
        HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict', diagnostics: 'no reminder is waiting' }] }, { status: 409 }),
      ),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY }), ctx);
    expect(response.status).toBe(409);
    expect(JSON.stringify(await response.json())).not.toMatch(/\d{4}$/);
  });
});
