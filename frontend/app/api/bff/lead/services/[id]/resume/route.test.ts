// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/services/s-ucr-east/resume';
const ctx = { params: Promise.resolve({ id: 's-ucr-east' }) };
const KEY = 'resume-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/services/[id]/resume', () => {
  it('answers 400 unless both confirmations are true, and does not call the back end', async () => {
    let called = false;
    server.use(http.post(`${BACKEND_BASE}/HealthcareService/s-ucr-east/$resume`, () => { called = true; return HttpResponse.json({}); }));
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { phonedRegisterNumber: true, reasonResolved: false } }), ctx);
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('sends both confirmations to $resume and answers the status and next due time', async () => {
    let sent: unknown;
    server.use(
      http.post(`${BACKEND_BASE}/HealthcareService/s-ucr-east/$resume`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({
          resourceType: 'Parameters',
          parameter: [
            { name: 'status', valueCode: 'active' },
            { name: 'nextDueAt', valueDateTime: '2026-10-30T16:00:00Z' },
          ],
        });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { phonedRegisterNumber: true, reasonResolved: true } }), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'active', nextDueAt: '2026-10-30T16:00:00Z' });
    expect(sent).toEqual({
      resourceType: 'Parameters',
      parameter: [
        { name: 'calledBack', valueBoolean: true },
        { name: 'reasonResolved', valueBoolean: true },
      ],
    });
  });
});
