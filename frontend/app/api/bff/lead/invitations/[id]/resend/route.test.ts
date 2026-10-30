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
const URL_ = 'https://app.test/api/bff/lead/invitations/inv-1/resend';
const ctx = { params: Promise.resolve({ id: 'inv-1' }) };
const KEY = 'resend-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/invitations/[id]/resend', () => {
  it('answers 403 to an advisor, and 400 with no key', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY }), ctx)).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true }), ctx)).status).toBe(400);
  });

  it('sends the invitation again at the back end with the key, and answers when it expires', async () => {
    let key: string | null = null;
    server.use(
      http.post(`${ROOT}/lead/invitations/inv-1/resend`, ({ request }) => {
        key = request.headers.get('idempotency-key');
        return HttpResponse.json({ invitationId: 'inv-1', registrationId: 'reg-1', expiresAt: '2026-11-01T09:00:00Z' });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY }), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ invitationId: 'inv-1', registrationId: 'reg-1', expiresAt: '2026-11-01T09:00:00Z' });
    expect(key).toBe(KEY);
  });

  it('answers 404 for an invitation that is not there', async () => {
    server.use(http.post(`${ROOT}/lead/invitations/inv-1/resend`, () => HttpResponse.json({}, { status: 404 })));
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY }), ctx)).status).toBe(404);
  });
});
