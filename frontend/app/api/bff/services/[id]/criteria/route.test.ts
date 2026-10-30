// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { CRITERIA_HISTORY } from '@/test/fixtures/backend-shapes';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const HISTORY_URL = `${BACKEND_BASE}/Basic`;
const seenQueries: (string | null)[] = [];

function session(role: Role): Session {
  return {
    role,
    tenantId: 'trust-a',
    host: 'app.test',
    services: [],
    sub: 'advisor-1',
    backendToken: 'token-for-advisor',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function get(role: Role | null, id = 'svc-ucr-west'): Promise<Response> {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return GET(requestWithCookies(`https://app.test/api/bff/services/${id}/criteria`, cookies), {
    params: Promise.resolve({ id }),
  });
}

function basic(id: string, version: number, status: string, reviewBy: string) {
  return {
    resource: {
      resourceType: 'Basic',
      id,
      meta: { versionId: String(version) },
      status,
      reviewBy,
      subject: { reference: 'HealthcareService/svc-ucr-west' },
    },
  };
}

beforeEach(() => {
  seenQueries.length = 0;
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.get(HISTORY_URL, ({ request }) => {
      seenQueries.push(new URL(request.url).searchParams.get('subject'));
      return HttpResponse.json({
        resourceType: 'Bundle',
        type: 'searchset',
        total: 2,
        entry: [basic('crit-2', 3, 'current', '2099-12-12'), basic('crit-1', 2, 'superseded', '2099-01-01')],
      });
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/services/[id]/criteria (W14)', () => {
  it('reads the history of the service and answers the current version, with its review date', async () => {
    const response = await get('advisor');

    expect(response.status).toBe(200);
    expect(seenQueries).toEqual(['HealthcareService/svc-ucr-west']);
    expect(await response.json()).toMatchObject({ version: 3, reviewBy: '2099-12-12', overdue: false });
  });

  it('words what the current version accepts and excludes, from the history the back end sends an advisor (W14)', async () => {
    server.use(http.get(HISTORY_URL, () => HttpResponse.json(CRITERIA_HISTORY)));

    expect(await (await get('advisor')).json()).toMatchObject({
      accepts: 'Fall, no injury · Frailty · Age 18+',
      excludes: 'Suspected fracture',
    });
  });

  it('flags criteria whose review date has passed', async () => {
    server.use(
      http.get(HISTORY_URL, () => HttpResponse.json({ resourceType: 'Bundle', entry: [basic('crit-2', 3, 'current', '2001-01-01')] })),
    );
    expect(await (await get('advisor')).json()).toMatchObject({ overdue: true });
  });

  it('answers 404 when the service has no criteria', async () => {
    server.use(http.get(HISTORY_URL, () => HttpResponse.json({ resourceType: 'Bundle', total: 0, entry: [] })));
    expect((await get('advisor')).status).toBe(404);
  });

  it('answers 403 for a reporter, and refuses a service id that cannot be one, before any read', async () => {
    expect((await get('reporter')).status).toBe(403);
    expect((await get('advisor', 'a%20b')).status).toBe(400);
    expect(seenQueries).toHaveLength(0);
  });

  it('is never cached', async () => {
    expect((await get('advisor')).headers.get('cache-control')).toBe('private, no-store');
  });
});
