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
const URL_ = 'https://app.test/api/bff/lead/invitations/inv-1/switch-to-text';
const ctx = { params: Promise.resolve({ id: 'inv-1' }) };
const KEY = 'switch-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/invitations/[id]/switch-to-text', () => {
  it('answers 403 to an advisor, and 403 with no CSRF header', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY }), ctx)).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', key: KEY }), ctx)).status).toBe(403);
  });

  it('switches the reporter to text at the back end with the key, and answers the channel', async () => {
    let key: string | null = null;
    server.use(
      http.post(`${ROOT}/lead/invitations/inv-1/switch-to-text`, ({ request }) => {
        key = request.headers.get('idempotency-key');
        return HttpResponse.json({ channel: 'text' });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY }), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ channel: 'text' });
    expect(key).toBe(KEY);
  });

  it('answers 409 when the reporter has no number to text', async () => {
    server.use(http.post(`${ROOT}/lead/invitations/inv-1/switch-to-text`, () => HttpResponse.json({}, { status: 409 })));
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY }), ctx)).status).toBe(409);
  });
});
