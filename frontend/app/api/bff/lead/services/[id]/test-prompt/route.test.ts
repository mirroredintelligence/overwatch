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
const URL_ = 'https://app.test/api/bff/lead/services/s-ucr-east/test-prompt';
const ctx = { params: Promise.resolve({ id: 's-ucr-east' }) };
const KEY = 'test-prompt-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/services/[id]/test-prompt', () => {
  it('answers 403 to an advisor, and 403 with no CSRF header', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY }), ctx)).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', key: KEY }), ctx)).status).toBe(403);
  });

  it('refuses a channel the back end does not know, a body field it does not take, and no key', async () => {
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { channel: 'fax' } }), ctx)).status).toBe(400);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { channel: 'text', tenantId: 'x' } }), ctx)).status).toBe(400);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true }), ctx)).status).toBe(400);
  });

  it('sends the test prompt to the back end and answers the channel and the last four digits only', async () => {
    let body: unknown;
    server.use(
      http.post(`${ROOT}/lead/services/s-ucr-east/test-prompt`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ channel: 'email', numberEnding: '0377' });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { channel: 'email' } }), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ channel: 'email', numberEnding: '0377' });
    expect(body).toEqual({ channel: 'email' });
  });

  it('answers 409 inside a minute of the last test', async () => {
    server.use(
      http.post(`${ROOT}/lead/services/s-ucr-east/test-prompt`, () =>
        HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict', diagnostics: 'too soon' }] }, { status: 409 }),
      ),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY }), ctx);
    expect(response.status).toBe(409);
  });
});
