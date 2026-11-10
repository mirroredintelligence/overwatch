// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

// Find a service through the BFF (DEC-1366). Browse only: the advisor and Advisor v2 may call it; the postcode, age
// band, needs and urgency are checked by shape, the postcode is sent in the body only (never a URL) and is not
// echoed in any answer.

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/advisor-v2/find';
const GOOD = { postcode: 'dt4 8xx', ageBand: '80+', needs: ['frailty', 'fall-no-injury'], urgency: 'today' };
const ANSWER = { generatedAt: '2026-11-10T14:00:00Z', notFound: false, services: [] };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

const post = async (role: Parameters<typeof leadRequest>[1], body: unknown = GOOD, csrf = true) =>
  POST(await leadRequest(URL_, role, { method: 'POST', csrf, body }));

describe('POST /api/bff/advisor-v2/find', () => {
  it('admits the advisor and Advisor v2 and no one else', async () => {
    server.use(http.post(`${ROOT}/advisor-v2/find`, () => HttpResponse.json(ANSWER)));
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
      http.post(`${ROOT}/advisor-v2/find`, async ({ request }) => {
        seen = { url: request.url, body: await request.json() };
        return HttpResponse.json(ANSWER);
      }),
    );
    await post('advisor-v2');
    expect(seen?.body).toEqual({ postcode: 'DT4 8XX', ageBand: '80+', needs: ['frailty', 'fall-no-injury'], urgency: 'today' });
    expect(seen?.url).not.toMatch(/DT4|8XX|postcode|frailty/i);
  });

  it('refuses a bad request with a 400 that does not repeat it, and calls nothing', async () => {
    let called = false;
    server.use(http.post(`${ROOT}/advisor-v2/find`, () => { called = true; return HttpResponse.json(ANSWER); }));
    for (const body of [
      { ...GOOD, postcode: 'not a postcode' },
      { ...GOOD, ageBand: '40' },
      { ...GOOD, needs: [] },
      { ...GOOD, needs: ['nonsense'] },
      { ...GOOD, urgency: 'soon' },
      { ...GOOD, tenant: 'other' },
    ]) {
      const response = await post('advisor-v2', body);
      expect(response.status).toBe(400);
      expect(JSON.stringify(await response.json())).not.toMatch(/not a postcode|nonsense/);
    }
    expect(called).toBe(false);
  });

  it('is an error, not an empty list, when the answer is not shaped like one', async () => {
    server.use(http.post(`${ROOT}/advisor-v2/find`, () => HttpResponse.json({ services: 'no' })));
    expect((await post('advisor-v2')).status).toBe(502);
  });

  it('answers private and not stored, and keeps no postcode in the answer', async () => {
    server.use(http.post(`${ROOT}/advisor-v2/find`, () => HttpResponse.json(ANSWER)));
    const response = await post('advisor-v2');
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    expect(JSON.stringify(await response.json())).not.toMatch(/DT4/);
  });
});
