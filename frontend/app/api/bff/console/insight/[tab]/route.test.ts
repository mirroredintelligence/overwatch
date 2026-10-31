// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role } from '@/lib/auth/session';
import {
  INSIGHT_FRICTION,
  INSIGHT_FUNNELS,
  INSIGHT_PATHS,
  INSIGHT_PERFORMANCE,
  INSIGHT_RELEASES,
} from '@/test/fixtures/insight-shapes';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const BACKEND_ROOT = 'http://backend.test';
const BASE = `https://${TENANTS.A.host}/api/bff/console/insight`;
const ANSWERS: Record<string, unknown> = {
  funnels: INSIGHT_FUNNELS,
  paths: INSIGHT_PATHS,
  friction: INSIGHT_FRICTION,
  performance: INSIGHT_PERFORMANCE,
  releases: INSIGHT_RELEASES,
};

async function get(role: Role | null, tab: string, query = '') {
  const cookies: Record<string, string> = {};
  if (role !== null) {
    cookies[SESSION_COOKIE] = await sealSession(sessionFor(TENANTS.A, role, { backendToken: 'token-of-the-support-user' }));
  }
  return GET(requestWithCookies(`${BASE}/${tab}${query}`, cookies), { params: Promise.resolve({ tab }) });
}

let seen: Array<{ path: string; search: string; authorization: string | null }>;

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  seen = [];
  server.use(
    http.get(`${BACKEND_ROOT}/support/insight/:tab`, ({ request, params }) => {
      const url = new URL(request.url);
      seen.push({ path: url.pathname, search: url.search, authorization: request.headers.get('authorization') });
      return HttpResponse.json(ANSWERS[String(params.tab)] as Record<string, unknown>);
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/console/insight/[tab]', () => {
  it.each(Object.keys(ANSWERS))('answers the %s tab with what the back end answered, from its root', async (tab) => {
    const response = await get('support', tab, '?range=7d');

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(ANSWERS[tab]);
    expect(seen[0]).toEqual({
      path: `/support/insight/${tab}`,
      search: '?range=7d',
      authorization: 'Bearer token-of-the-support-user',
    });
  });

  it('asks for seven days when no range is given, and passes a device that is on the list', async () => {
    await get('support', 'friction');
    await get('support', 'performance', '?range=24h&device=phone');

    expect(seen.map((call) => call.search)).toEqual(['?range=7d', '?range=24h&device=phone']);
  });

  it.each([
    ['sessions', '?range=7d'],
    ['funnels', '?range=1y'],
    ['funnels', '?range=7d&device=watch'],
    ['funnels', '?range=7d&device='],
  ])('refuses %s %s before the back end is asked', async (tab, query) => {
    const response = await get('support', tab, query);

    expect(response.status).toBe(400);
    expect(seen).toEqual([]);
  });

  it('forwards the range and device only: nothing else the browser sends reaches the back end', async () => {
    await get('support', 'funnels', '?range=7d&note=hello&sessionId=abc123');

    expect(seen[0]?.search).toBe('?range=7d');
  });

  it('refuses a request that names a tenant, and asks the back end for nothing (TEN-044)', async () => {
    const response = await get('support', 'funnels', '?range=7d&tenantId=tenant-b');

    expect(response.status).toBe(400);
    expect(seen).toEqual([]);
  });

  it('does not send the device to the release comparison, which has none', async () => {
    await get('support', 'releases', '?range=7d&device=phone');

    expect(seen[0]?.search).toBe('?range=7d');
  });

  it.each<Role>(['advisor', 'lead', 'exec', 'owner', 'reporter', 'audit'])(
    'refuses a %s session before the back end is asked',
    async (role) => {
      const response = await get(role, 'funnels', '?range=7d');

      expect(response.status).toBe(403);
      expect(seen).toEqual([]);
    },
  );

  it('answers 401 with no session', async () => {
    expect((await get(null, 'funnels', '?range=7d')).status).toBe(401);
  });

  it('says the back end is unavailable when it fails, never an empty answer', async () => {
    server.use(http.get(`${BACKEND_ROOT}/support/insight/:tab`, () => HttpResponse.json({ code: 'x' }, { status: 503 })));

    const response = await get('support', 'funnels', '?range=7d');

    expect(response.status).toBeGreaterThanOrEqual(500);
    expect(response.headers.get('cache-control')).toContain('no-store');
  });
});
