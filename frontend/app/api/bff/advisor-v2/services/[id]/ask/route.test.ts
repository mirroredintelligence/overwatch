// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

// Ask a service for its capacity from the advisor's service page (DEC-1377). The advisor, Advisor v2, the shift lead and
// the clinical advisor may ask; anyone else is refused.

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/advisor-v2/services/svc-a/ask';
const BACK = `${ROOT}/advisor-v2/services/svc-a/ask`;
const ctx = { params: Promise.resolve({ id: 'svc-a' }) };
const KEY = 'ask-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

const post = async (
  role: Parameters<typeof leadRequest>[1],
  options: { csrf?: boolean; key?: string } = { csrf: true, key: KEY },
) => POST(await leadRequest(URL_, role, { method: 'POST', ...options }), ctx);

describe('POST /api/bff/advisor-v2/services/[id]/ask', () => {
  it('admits the advisor, Advisor v2, the shift lead and the clinical advisor and no one else', async () => {
    server.use(http.post(BACK, () => HttpResponse.json({ queued: true })));
    for (const role of ['advisor', 'advisor-v2', 'lead', 'clinical'] as const) {
      expect((await post(role)).status).toBe(200);
    }
    for (const role of ['exec', 'analytics-user', 'owner', 'reporter'] as const) {
      expect((await post(role)).status).toBe(403);
    }
    expect((await post(null)).status).toBe(401);
  });

  it('needs the CSRF header and an Idempotency-Key, and calls nothing without them', async () => {
    let called = false;
    server.use(
      http.post(BACK, () => {
        called = true;
        return HttpResponse.json({ queued: true });
      }),
    );
    expect((await post('advisor', { csrf: false, key: KEY })).status).toBe(403);
    expect((await post('advisor', { csrf: true })).status).toBe(400);
    expect(called).toBe(false);
  });

  it('passes the key on and answers that it was queued', async () => {
    let key: string | null = null;
    server.use(
      http.post(BACK, ({ request }) => {
        key = request.headers.get('idempotency-key');
        return HttpResponse.json({ queued: true, dueAt: '2026-11-10T14:00:00Z' });
      }),
    );
    const response = await post('advisor');
    expect(await response.json()).toEqual({ queued: true, dueAt: '2026-11-10T14:00:00Z' });
    expect(key).toBe(KEY);
  });

  it('passes a 409 on and does not turn it into a success', async () => {
    server.use(
      http.post(BACK, () =>
        HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict' }] }, { status: 409 }),
      ),
    );
    expect((await post('advisor')).status).toBe(409);
  });
});
