// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { ANALYTICS_BACKEND_ANSWER, ANALYTICS_OVERVIEW, ANALYTICS_OVERVIEW_AREAS } from '@/test/fixtures/analytics';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/analytics/overview';
const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/analytics/overview', () => {
  it('answers 403 to every role but the Analytics User, and 401 with no session', async () => {
    for (const role of ['advisor', 'lead', 'exec', 'owner', 'audit', 'wall', 'advisor-v2'] as const) {
      const response = await GET(await leadRequest(URL_, role));
      expect(response.status, role).toBe(403);
    }
    expect((await GET(await leadRequest(URL_, null))).status).toBe(401);
  });

  it('reads the overview with the session token and passes the checked answer on, private and not stored', async () => {
    let auth: string | null = null;
    server.use(
      http.get(`${ROOT}/analytics/overview`, ({ request }) => {
        auth = request.headers.get('authorization');
        return HttpResponse.json(ANALYTICS_BACKEND_ANSWER, { headers: { 'Cache-Control': 'no-store' } });
      }),
    );
    const response = await GET(await leadRequest(URL_, 'analytics-user'));
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    expect(auth).toBe('Bearer token-for-the-lead');
    expect(await response.json()).toEqual(ANALYTICS_OVERVIEW);
  });

  it('takes no tenant from the request', async () => {
    const response = await GET(await leadRequest(`${URL_}?tenant=other`, 'analytics-user'));
    expect(response.status).toBeGreaterThanOrEqual(400);
    expect(response.status).toBeLessThan(500);
  });

  it('answers 500 for an answer it does not know, and 503 when the back end is down, never an empty page', async () => {
    server.use(http.get(`${ROOT}/analytics/overview`, () => HttpResponse.json({ services: [] })));
    const bad = await GET(await leadRequest(URL_, 'analytics-user'));
    expect(bad.status).toBe(500);
    expect(await bad.json()).not.toHaveProperty('services');
    server.use(http.get(`${ROOT}/analytics/overview`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 503 })));
    expect((await GET(await leadRequest(URL_, 'analytics-user'))).status).toBe(503);
  });
});

describe('the areas in the answer (DEC-1375)', () => {
  it('passes the areas and each service\'s one area on, and keeps only the known fields of an area', async () => {
    const answer = { ...ANALYTICS_OVERVIEW_AREAS, areas: ANALYTICS_OVERVIEW_AREAS.areas.map((area) => ({ ...area, boundary: 'x', tenantId: 't' })) };
    server.use(http.get(`${ROOT}/analytics/overview`, () => HttpResponse.json(answer)));
    const response = await GET(await leadRequest(URL_, 'analytics-user'));
    expect(response.status).toBe(200);
    const body = (await response.json()) as typeof ANALYTICS_OVERVIEW_AREAS;
    expect(body).toEqual(ANALYTICS_OVERVIEW_AREAS);
    expect(JSON.stringify(body)).not.toContain('boundary');
  });
});
