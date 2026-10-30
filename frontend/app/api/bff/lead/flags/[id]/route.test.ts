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

const URL_ = 'https://app.test/api/bff/lead/flags/flag-1';
const ctx = { params: Promise.resolve({ id: 'flag-1' }) };
const KEY = 'flag-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/flags/[id]', () => {
  it('answers 400 for an action it does not know, and for suspension (which is a service action)', async () => {
    for (const action of ['suspend', 'delete']) {
      const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { action } }), ctx);
      expect(response.status).toBe(400);
    }
  });

  it('sends accept as the accepted outcome to $resolve, and answers the outcome', async () => {
    let sent: unknown;
    server.use(
      http.post(`${BACKEND_ROOT}/admin/report-flags/flag-1/$resolve`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({
          resourceType: 'Parameters',
          parameter: [
            { name: 'flagId', valueString: 'flag-1' },
            { name: 'status', valueString: 'closed' },
            { name: 'outcome', valueString: 'accepted' },
          ],
        });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { action: 'accept' } }), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ flagId: 'flag-1', outcome: 'accepted' });
    expect(sent).toEqual({ resourceType: 'Parameters', parameter: [{ name: 'outcome', valueString: 'accepted' }] });
  });

  it('sends checked as the checked outcome', async () => {
    let sent: unknown;
    server.use(
      http.post(`${BACKEND_ROOT}/admin/report-flags/flag-1/$resolve`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ resourceType: 'Parameters', parameter: [{ name: 'outcome', valueString: 'checked' }] });
      }),
    );
    await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { action: 'checked' } }), ctx);
    expect(sent).toEqual({ resourceType: 'Parameters', parameter: [{ name: 'outcome', valueString: 'checked' }] });
  });
});
