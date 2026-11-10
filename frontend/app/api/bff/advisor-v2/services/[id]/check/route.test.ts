// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

// Check one patient against one service through the BFF (DEC-1377). Browse only: the advisor and Advisor v2 may call
// it; the criteria are checked by shape, the postcode goes in the body only and is not echoed.

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/advisor-v2/services/svc-a/check';
const BACK = `${ROOT}/advisor-v2/services/svc-a/check`;
const ctx = { params: Promise.resolve({ id: 'svc-a' }) };
const GOOD = { postcode: 'dt4 8xx', ageBand: '80+', needs: ['frailty'], urgency: 'today' };
const FITS = { serviceId: 'svc-a', fits: true, reasons: [], fitsNeeds: ['frailty'], warnings: [], phone: null };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

const post = async (role: Parameters<typeof leadRequest>[1], body: unknown = GOOD, csrf = true) =>
  POST(await leadRequest(URL_, role, { method: 'POST', csrf, body }), ctx);

describe('POST /api/bff/advisor-v2/services/[id]/check', () => {
  it('admits the advisor and Advisor v2 and no one else', async () => {
    server.use(http.post(BACK, () => HttpResponse.json(FITS)));
    expect((await post('advisor')).status).toBe(200);
    expect((await post('advisor-v2')).status).toBe(200);
    for (const role of ['lead', 'clinical', 'exec', 'analytics-user', 'owner'] as const) {
      expect((await post(role)).status).toBe(403);
    }
    expect((await post(null)).status).toBe(401);
  });

  it('needs the CSRF header', async () => {
    expect((await post('advisor-v2', GOOD, false)).status).toBe(403);
  });

  it('sends the normalised postcode and the codes in the body, and nothing in the address', async () => {
    let seen: { url: string; body: unknown } | undefined;
    server.use(
      http.post(BACK, async ({ request }) => {
        seen = { url: request.url, body: await request.json() };
        return HttpResponse.json(FITS);
      }),
    );
    await post('advisor-v2');
    expect(seen?.body).toEqual({ postcode: 'DT4 8XX', ageBand: '80+', needs: ['frailty'], urgency: 'today' });
    expect(seen?.url).not.toMatch(/DT4|8XX|postcode|frailty/i);
  });

  it('refuses a bad request with a 400 that does not repeat it, and calls nothing', async () => {
    let called = false;
    server.use(
      http.post(BACK, () => {
        called = true;
        return HttpResponse.json(FITS);
      }),
    );
    for (const body of [
      { ...GOOD, postcode: 'not a postcode' },
      { ...GOOD, ageBand: '40' },
      { ...GOOD, needs: [] },
      { ...GOOD, needs: ['nonsense'] },
      { ...GOOD, urgency: 'soon' },
    ]) {
      const response = await post('advisor-v2', body);
      expect(response.status).toBe(400);
      expect(JSON.stringify(await response.json())).not.toMatch(/not a postcode|nonsense/);
    }
    expect(called).toBe(false);
  });

  it('is an error, not a fit, when the answer is not shaped like one', async () => {
    server.use(http.post(BACK, () => HttpResponse.json({ serviceId: 'svc-a', reasons: [] })));
    expect((await post('advisor-v2')).status).toBe(502);
  });

  it('answers private and not stored, and keeps the postcode out of the answer', async () => {
    server.use(http.post(BACK, () => HttpResponse.json(FITS)));
    const response = await post('advisor-v2');
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    expect(JSON.stringify(await response.json())).not.toMatch(/DT4/);
  });
});
