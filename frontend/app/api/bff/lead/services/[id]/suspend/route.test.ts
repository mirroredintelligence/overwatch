// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/services/s-ucr-east/suspend';
const ctx = { params: Promise.resolve({ id: 's-ucr-east' }) };
const KEY = 'suspend-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/services/[id]/suspend', () => {
  it('answers 403 without the CSRF header', async () => {
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', key: KEY, body: { reason: 'other' } }), ctx)).status).toBe(403);
  });

  it('answers 403 to an advisor', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY, body: { reason: 'other' } }), ctx)).status).toBe(403);
  });

  it('answers 400 for a reason the back end does not know, and does not call it', async () => {
    let called = false;
    server.use(http.post(`${BACKEND_BASE}/HealthcareService/s-ucr-east/$suspend`, () => { called = true; return HttpResponse.json({}); }));
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { reason: 'boredom' } }), ctx);
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('sends the reason to $suspend with the key, and answers when, and how many requests expired', async () => {
    let sent: { body: unknown; key: string | null } | undefined;
    server.use(
      http.post(`${BACKEND_BASE}/HealthcareService/s-ucr-east/$suspend`, async ({ request }) => {
        sent = { body: await request.json(), key: request.headers.get('idempotency-key') };
        return HttpResponse.json({
          resourceType: 'Parameters',
          parameter: [
            { name: 'expiredRequests', valueInteger: 2 },
            { name: 'notified', valueBoolean: true },
          ],
        });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { reason: 'closed-unexpectedly' } }), ctx);
    expect(response.status).toBe(200);
    const answer = (await response.json()) as { since: string; expiredRequests: number; notified: boolean };
    expect(answer.expiredRequests).toBe(2);
    expect(answer.notified).toBe(true);
    expect(Number.isNaN(Date.parse(answer.since))).toBe(false);
    expect(sent?.key).toBe(KEY);
    expect(sent?.body).toEqual({
      resourceType: 'Parameters',
      parameter: [{ name: 'reason', valueCode: 'closed-unexpectedly' }],
    });
  });
});
