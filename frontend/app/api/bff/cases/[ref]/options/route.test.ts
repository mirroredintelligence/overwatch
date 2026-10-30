// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { OPTIONS_PARAMETERS, OPTIONS_VIEW } from '@/test/fixtures/options';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const FILTER_URL = `${BACKEND_BASE}/HealthcareService/$filter-options`;
type Seen = { body: unknown; key: string | null; token: string | null };
const seen: Seen[] = [];

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

async function get(role: Role | null, ref = '4821'): Promise<Response> {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return GET(requestWithCookies(`https://app.test/api/bff/cases/${ref}/options`, cookies), {
    params: Promise.resolve({ ref }),
  });
}

beforeEach(() => {
  seen.length = 0;
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.post(FILTER_URL, async ({ request }) => {
      seen.push({
        body: await request.clone().json(),
        key: request.headers.get('idempotency-key'),
        token: request.headers.get('authorization'),
      });
      return HttpResponse.json(OPTIONS_PARAMETERS);
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/cases/[ref]/options (W13)', () => {
  it('calls $filter-options once for the case, with a key for this read and the session token', async () => {
    const response = await get('advisor');

    expect(response.status).toBe(200);
    expect(seen).toHaveLength(1);
    expect(seen[0].body).toEqual({
      resourceType: 'Parameters',
      parameter: [{ name: 'case', valueReference: { reference: 'ServiceRequest/4821' } }],
    });
    expect(seen[0].key).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(seen[0].token).toBe('Bearer token-for-advisor');
  });

  it('answers the options view in the back end order, with the not-suitable list', async () => {
    const body = (await (await get('advisor')).json()) as {
      shownAt: unknown;
      options: { serviceId: string; name: string; status: string; travelText: string | null }[];
      notSuitable: unknown;
    };

    expect(body.options.map((option) => option.serviceId)).toEqual(OPTIONS_VIEW.options.map((o) => o.serviceId));
    expect(body.options[0]).toMatchObject({ name: 'UCR West', status: 'accepting', travelText: 'about 35 to 50 min' });
    expect(body.notSuitable).toEqual(OPTIONS_VIEW.notSuitable);
    expect(typeof body.shownAt).toBe('string');
  });

  it('answers 403 for a reporter and calls nothing', async () => {
    expect((await get('reporter')).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('refuses a case reference that cannot be a case id, before any call', async () => {
    expect((await get('advisor', 'a%20b')).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('answers 502 when the back end sends something that is not Parameters', async () => {
    server.use(http.post(FILTER_URL, () => HttpResponse.json({ resourceType: 'Bundle' })));
    expect((await get('advisor')).status).toBe(502);
  });

  it('is never cached', async () => {
    expect((await get('advisor')).headers.get('cache-control')).toBe('private, no-store');
  });

  it('a tenant named in the address is refused with 400 and the back end is not called (DEC-130, TEN-044)', async () => {
    const cookies = { [SESSION_COOKIE]: await sealSession(session('advisor')) };
    const response = await GET(
      requestWithCookies('https://app.test/api/bff/cases/4821/options?tenantId=tenant-b', cookies),
      { params: Promise.resolve({ ref: '4821' }) },
    );

    expect(response.status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('an organisation named in the address is ignored: the back end sees the session token and the case only (DEC-130)', async () => {
    const cookies = { [SESSION_COOKIE]: await sealSession(session('advisor')) };
    await GET(
      requestWithCookies('https://app.test/api/bff/cases/4821/options?organisation=other', cookies),
      { params: Promise.resolve({ ref: '4821' }) },
    );

    expect(seen).toHaveLength(1);
    expect(seen[0].token).toBe('Bearer token-for-advisor');
    expect(JSON.stringify(seen[0].body)).not.toMatch(/tenant|organisation|other/);
  });
});
