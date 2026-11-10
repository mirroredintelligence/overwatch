// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/services/s-ucr-east/retire';
const ctx = { params: Promise.resolve({ id: 's-ucr-east' }) };
const KEY = 'retire-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/services/[id]/retire', () => {
  it('answers 403 without the CSRF header', async () => {
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', key: KEY }), ctx)).status).toBe(403);
  });

  it('answers 403 to an advisor', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY }), ctx)).status).toBe(403);
  });

  it('calls $retire with the key and answers how many open requests expired', async () => {
    let sent: { key: string | null } | undefined;
    server.use(
      http.post(`${BACKEND_BASE}/HealthcareService/s-ucr-east/$retire`, ({ request }) => {
        sent = { key: request.headers.get('idempotency-key') };
        return HttpResponse.json({ resourceType: 'Parameters', parameter: [{ name: 'expiredRequests', valueInteger: 2 }] });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY }), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ expiredRequests: 2 });
    expect(sent?.key).toBe(KEY);
  });
});
