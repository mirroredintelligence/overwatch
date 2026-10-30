// @vitest-environment node
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Role } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { EXEC_BACKEND } from '@/test/msw/handlers/exec';
import { requestAs } from '@/test/requests';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { GET as exportGet } from './export/route';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const ROOT = EXEC_BACKEND.replace(/\/fhir$/, '');
const seen: string[] = [];
const ANSWER = {
  cohort: 'Cohort: age 65+, all needs, within 2 hrs, ambulance crew or care home referrers. Groups under 10 are hidden.',
  referrals: { count: 640, suppressed: false },
  bestFitUnavailable: { count: 112, pct: 18, suppressed: false },
  wentElsewhere: { count: 62, suppressed: false },
  flows: [
    { bestFit: 'Falls team', state: 'full', wentTo: 'Community beds', count: 41, suppressed: false },
    { bestFit: 'Frailty ward', state: 'not updated', wentTo: 'no destination recorded', count: null, suppressed: true },
  ],
  grid: Array.from({ length: 7 }, () => [null, null, null, null]),
  busiest: null,
  declinedDespite: [{ service: 'Ward A', count: null, suppressed: true }],
};

const get = async (query: string, role: Role = 'lead', handler: typeof GET = GET) =>
  handler(await requestAs(TENANTS.A, role, { path: `/api/bff/planning${query}` }));

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  seen.length = 0;
  // The planning route is at the back end's root (routes_planning.py), not under /fhir.
  server.use(http.get(`${ROOT}/planning`, (({ request }) => {
    seen.push(new URL(request.url).search.slice(1));
    return HttpResponse.json(ANSWER);
  }) as HttpResponseResolver));
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/planning', () => {
  it('passes the period and need to the back end and answers what it answers', async () => {
    const response = await get('?period=30d&need=falls-frailty');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(ANSWER);
    expect(seen).toEqual(['period=30d&need=falls-frailty']);
  });

  it('defaults to the last 90 days and all needs', async () => {
    await get('');
    expect(seen).toEqual(['period=90d&need=all']);
  });

  it('refuses a period or need that is not listed, with no back-end call', async () => {
    expect((await get('?period=7d')).status).toBe(400);
    expect((await get('?need=everyone')).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('is open to a lead and an executive, and refuses every other role', async () => {
    expect((await get('', 'exec')).status).toBe(200);
    for (const role of ['advisor', 'clinical', 'owner', 'reporter', 'support'] as const) {
      expect((await get('', role)).status).toBe(403);
    }
  });

  it('says it is unavailable when the back end fails, never an empty analysis', async () => {
    server.use(http.get(`${ROOT}/planning`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'exception', diagnostics: 'x' }] }, { status: 503 })));
    expect((await get('')).status).toBe(503);
  });
});

describe('GET /api/bff/planning/export', () => {
  it('writes the flows and the declined rows as CSV, a hidden count as an empty field', async () => {
    const response = await get('?period=90d&need=all', 'lead', exportGet);
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toContain('text/csv');
    expect(await response.text()).toBe(
      [
        'Section,Best fit,State,Went to,Referrals',
        'Flow,Falls team,full,Community beds,41',
        'Flow,Frailty ward,not updated,no destination recorded,',
        'Declined,Ward A,,,',
        '',
      ].join('\r\n'),
    );
  });
});
