// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER, csrfTokenFor } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { CASE_REF, SERVICE_ID, STATE_REQUESTED } from '@/test/fixtures/bookings';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/msw/server';
import { BACKEND_TASK_HANDLERS, seenTaskSearches } from '@/test/msw/handlers/bookings';
import { GET, POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const BACKEND = 'http://backend.test/fhir';
const URL_ = 'https://app.test/api/bff/bookings';
const KEY = '9f1c2b3a-4d5e-4f60-8a7b-1c2d3e4f5a6b';
const TOKEN = 'token-for-advisor-one';
// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF_VALUE = await csrfTokenFor({ tenantId: 'trust-a', host: 'app.test', sub: 'advisor-1' }, 'N'.repeat(43));

function session(role: Role): Session {
  return {
    role,
    tenantId: 'trust-a',
    host: 'app.test',
    services: [],
    sub: 'advisor-1',
    backendToken: TOKEN,
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

type Options = { role?: Role | null; key?: string | null; csrf?: string | null; body?: unknown; raw?: string };

async function post(options: Options = {}) {
  const role = options.role === undefined ? 'advisor' : options.role;
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  const csrf = options.csrf === undefined ? CSRF_VALUE : options.csrf;
  if (csrf !== null) cookies[CSRF_COOKIE] = csrf;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (options.key !== null) headers['Idempotency-Key'] = options.key ?? KEY;
  if (csrf !== null) headers[CSRF_HEADER] = csrf;
  const body = options.raw ?? JSON.stringify(options.body ?? { caseRef: CASE_REF, serviceId: SERVICE_ID });
  return POST(requestWithCookies(URL_, cookies, { method: 'POST', headers, body }));
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  server.use(...BACKEND_TASK_HANDLERS(BACKEND));
});

describe('POST /api/bff/bookings', () => {
  it('refuses a request with no session', async () => {
    expect((await post({ role: null })).status).toBe(401);
  });

  it('refuses a role that may not request a booking', async () => {
    expect((await post({ role: 'reporter' })).status).toBe(403);
  });

  it('refuses a request with no CSRF header', async () => {
    expect((await post({ csrf: null })).status).toBe(403);
  });

  it('refuses a request with no Idempotency-Key, before the back end is called', async () => {
    const response = await post({ key: null });
    expect(response.status).toBe(400);
  });

  it('refuses any field that is not caseRef or serviceId, such as a tenant', async () => {
    const response = await post({ body: { caseRef: CASE_REF, serviceId: SERVICE_ID, tenantId: 'tenant-b' } });
    expect(response.status).toBe(400);
    expect(JSON.stringify(await response.json())).not.toContain('tenant-b');
  });

  it('opens the request at the back end with the session token and the key, and answers the booking state', async () => {
    const response = await post();
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual(STATE_REQUESTED);
    expect(response.headers.get('Cache-Control')).toBe('private, no-store');
  });

  it('answers 409 open-request when the service already has a request waiting', async () => {
    const response = await post({ body: { caseRef: CASE_REF, serviceId: 'ucr-busy' } });
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ code: 'open-request' });
  });
});


async function get(query: string, role: Role | null = 'advisor') {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return GET(requestWithCookies(`${URL_}${query}`, cookies));
}

describe('GET /api/bff/bookings?case=', () => {
  beforeEach(() => {
    seenTaskSearches.length = 0;
  });

  it('refuses a request with no session', async () => {
    expect((await get(`?case=${CASE_REF}`, null)).status).toBe(401);
  });

  it.each(['reporter', 'lead', 'clinical'] as const)('refuses the role %s', async (role) => {
    expect((await get(`?case=${CASE_REF}`, role)).status).toBe(403);
  });

  it('answers the bookings of the case as booking states, from the back end search with the session token', async () => {
    const response = await get(`?case=${CASE_REF}`);
    expect(response.status).toBe(200);
    const body = (await response.json()) as { bookings: { id: string; status: string }[] };
    expect(body.bookings.map((b) => b.status)).toEqual(['requested', 'confirmed']);
    expect(Object.keys(body)).toEqual(['bookings']);
    expect(seenTaskSearches).toEqual([`?focus=ServiceRequest%2F${CASE_REF}`]);
    expect(response.headers.get('Cache-Control')).toBe('private, no-store');
  });

  it('answers an empty list for a case with no booking', async () => {
    const response = await get('?case=case-none');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ bookings: [] });
  });

  it.each(['?case=a/b', '?case=', '?case=x&alert=open', '?case=x&tenant=t', '?other=1', '', '?alert=closed'])(
    'refuses the query %s before the back end is asked',
    async (query) => {
      expect((await get(query)).status).toBe(400);
      expect(seenTaskSearches).toEqual([]);
    },
  );
});

describe('GET /api/bff/bookings?alert=open (H-496)', () => {
  beforeEach(() => {
    seenTaskSearches.length = 0;
  });

  it('answers the open alerts: the withdrawals and not-reached reports nobody has answered', async () => {
    const response = await get('?alert=open');
    expect(response.status).toBe(200);
    const body = (await response.json()) as { bookings: { status: string; caseRef: string }[] };
    expect(body.bookings).toHaveLength(1);
    expect(body.bookings[0]).toMatchObject({ status: 'withdrawn', caseRef: CASE_REF });
    expect(seenTaskSearches).toEqual(['?alert=open']);
  });

  it('refuses a role that is not the advisor', async () => {
    expect((await get('?alert=open', 'reporter')).status).toBe(403);
  });

  it('does not hide a back-end failure as an empty list of alerts', async () => {
    server.use(http.get(`${BACKEND}/Task`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 500 })));
    expect((await get('?alert=open')).status).toBeGreaterThanOrEqual(500);
  });
});
