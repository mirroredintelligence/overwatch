// @vitest-environment node
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Role } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { EXEC_BACKEND } from '@/test/msw/handlers/exec';
import { requestAs } from '@/test/requests';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const ROOT = EXEC_BACKEND.replace(/\/fhir$/, '');
const seen: { search: string; auth: string | null }[] = [];
const ANSWER = {
  window: 'night',
  districts: [
    { district: 'DT3', services: ['UCR West', 'UCR East'] },
    { district: 'DT5', services: [] },
  ],
  uncovered: { count: null, suppressed: true, days: 90 },
};

const get = async (query: string, role: Role = 'lead') => GET(await requestAs(TENANTS.A, role, { path: `/api/bff/planning/coverage${query}` }));

let backendAnswer: unknown;

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  seen.length = 0;
  backendAnswer = ANSWER;
  // The coverage route is at the back end's root, as /planning is (not under /fhir).
  server.use(
    http.get(`${ROOT}/planning/coverage`, (({ request }) => {
      seen.push({ search: new URL(request.url).search.slice(1), auth: request.headers.get('authorization') });
      return HttpResponse.json(backendAnswer as object);
    }) as HttpResponseResolver),
  );
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/planning/coverage', () => {
  it('passes the window to the back end with the person’s token, and answers what it read', async () => {
    const response = await get('?window=night');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(ANSWER);
    expect(seen).toHaveLength(1);
    expect(seen[0].search).toBe('window=night');
    expect(seen[0].auth).toMatch(/^Bearer /);
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it('defaults to the whole day', async () => {
    await get('');
    expect(seen[0].search).toBe('window=all');
  });

  it('refuses a window that is not listed, with no back-end call', async () => {
    expect((await get('?window=noon')).status).toBe(400);
    expect((await get('?window=night&window=x')).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('sends on only what it read: a field the screen does not show does not pass through', async () => {
    backendAnswer = { ...ANSWER, secret: 'x', districts: [{ district: 'DT3', services: ['UCR West'], tenant: 't-1' }] };
    const body = await (await get('?window=night')).json();
    expect(body).toEqual({ ...ANSWER, districts: [{ district: 'DT3', services: ['UCR West'] }] });
  });

  it('answers 502 when the back end’s answer is not the shape expected, never a guess', async () => {
    backendAnswer = { window: 'night', districts: 'many' };
    expect((await get('?window=night')).status).toBe(502);
  });

  it('answers the back end’s 404 as a 404 (the route is not built there yet)', async () => {
    server.use(http.get(`${ROOT}/planning/coverage`, () => new HttpResponse(null, { status: 404 })));
    expect((await get('?window=night')).status).toBe(404);
  });

  it('is open to a lead and an executive, and refuses every other role', async () => {
    expect((await get('?window=all', 'lead')).status).toBe(200);
    expect((await get('?window=all', 'exec')).status).toBe(200);
    for (const role of ['advisor', 'owner', 'clinical', 'support'] as const) expect((await get('?window=all', role)).status).toBe(403);
  });

  it('refuses a request that names a tenant', async () => {
    expect((await get('?window=all&tenant=t-2')).status).toBeGreaterThanOrEqual(400);
    expect(seen).toHaveLength(0);
  });
});
