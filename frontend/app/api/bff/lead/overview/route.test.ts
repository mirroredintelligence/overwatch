// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/overview';
// The back end's root (the overview is not under /fhir, DEC-087).
const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/overview', () => {
  it('answers 403 to an advisor, who may not see the lead page', async () => {
    const response = await GET(await leadRequest(URL_, 'advisor'));
    expect(response.status).toBe(403);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
  });

  it('answers 401 with no session', async () => {
    expect((await GET(await leadRequest(URL_, null))).status).toBe(401);
  });

  it('reads the overview from the back end root for a lead and passes its answer on', async () => {
    let auth: string | null = null;
    server.use(
      http.get(`${ROOT}/lead/overview`, ({ request }) => {
        auth = request.headers.get('authorization');
        return HttpResponse.json(backEndShape(), { headers: { 'Cache-Control': 'no-store' } });
      }),
    );
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    expect(auth).toBe('Bearer token-for-the-lead');
    expect(await response.json()).toEqual(OVERVIEW_SHIFT_LEAD);
  });

  it('answers 503 when the back end cannot be reached, and never an empty overview', async () => {
    server.use(http.get(`${ROOT}/lead/overview`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 503 })));
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(503);
    expect(await response.json()).not.toHaveProperty('chasing');
  });

  it('answers 500 when the back end answer is not the overview the page knows, and never a partly filled page', async () => {
    server.use(http.get(`${ROOT}/lead/overview`, () => HttpResponse.json({ chasing: [] })));
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(500);
    expect(await response.json()).not.toHaveProperty('chasing');
  });
});

// The overview as the back end writes it (routes_lead_views.py, camelCase; counts keyed by word).
function backEndShape() {
  return {
    chasing: OVERVIEW_SHIFT_LEAD.chasing,
    gettingOld: OVERVIEW_SHIFT_LEAD.gettingOld,
    covering: OVERVIEW_SHIFT_LEAD.covering,
    counts: OVERVIEW_SHIFT_LEAD.counts,
    reportingToday: OVERVIEW_SHIFT_LEAD.reportingToday,
  };
}
