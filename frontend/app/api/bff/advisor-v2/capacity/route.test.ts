// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET } from './route';

// The capacity overview of Advisor v2 through the BFF (DEC-1366): the advisor and Advisor v2 only; a malformed answer
// is an error, never an empty overview.

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/advisor-v2/capacity';
const ANSWER = {
  generatedAt: '2026-11-10T14:00:00Z',
  counts: { accepting: 1, limited: 0, notAccepting: 0, overCapacity: 0, notUpdated: 0 },
  attentionShown: 3,
  underPressure: [],
  underutilised: [],
  services: [],
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

const get = async (role: Parameters<typeof leadRequest>[1]) => GET(await leadRequest(URL_, role));

describe('GET /api/bff/advisor-v2/capacity', () => {
  it('admits the advisor and Advisor v2 and no one else', async () => {
    server.use(http.get(`${ROOT}/advisor-v2/capacity`, () => HttpResponse.json(ANSWER)));
    expect((await get('advisor')).status).toBe(200);
    const response = await get('advisor-v2');
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    expect(await response.json()).toEqual(ANSWER);
    for (const role of ['lead', 'clinical', 'exec', 'analytics-user', 'wall'] as const) {
      expect((await get(role)).status).toBe(403);
    }
    expect((await get(null)).status).toBe(401);
  });

  it('is an error when the answer is not shaped like an overview', async () => {
    server.use(http.get(`${ROOT}/advisor-v2/capacity`, () => HttpResponse.json({ counts: 'no' })));
    expect((await get('advisor')).status).toBe(502);
  });
});

describe('the areas in the answer (DEC-1375)', () => {
  it('passes the areas and each service\'s area on unchanged', async () => {
    const withAreas = {
      ...ANSWER,
      areas: [{ id: 'area-one', name: 'Area One', places: 'Alpha · Beta' }],
      services: [{ serviceId: 's', name: 'S', category: 'inpatient-beds', status: 'accepting', area: 'area-one', districts: [] }],
    };
    server.use(http.get(`${ROOT}/advisor-v2/capacity`, () => HttpResponse.json(withAreas)));
    const response = await get('advisor-v2');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(withAreas);
  });
});
