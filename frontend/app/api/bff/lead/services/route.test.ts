// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET, POST } from './route';
import { csrfOf } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = await csrfOf(TENANTS.A, 'user-1');
const URL_ = `https://${TENANTS.A.host}/api/bff/lead/services`;
const KEY = 'lead-setup-key-0001';

function session(role: Role): Session {
  return {
    role,
    tenantId: TENANTS.A.id,
    host: TENANTS.A.host,
    services: [],
    sub: 'user-1',
    backendToken: 'token-for-the-lead',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function request(method: 'GET' | 'POST', role: Role | null, options: { csrf?: boolean; key?: string | null; body?: unknown } = {}) {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  const headers: Record<string, string> = {};
  if (options.csrf) {
    cookies[CSRF_COOKIE] = CSRF;
    headers[CSRF_HEADER] = CSRF;
  }
  if (options.key) headers['Idempotency-Key'] = options.key;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  return requestWithCookies(URL_, cookies, {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
}

const VALID_BODY = {
  name: 'Reablement',
  category: 'reablement',
  measure: 'referrals-acceptable',
  unitLabel: 'referrals in the next 2 hrs',
  establishedCapacity: 4,
  usualMin: 0,
  usualMax: 8,
  cadence: 'every-2-hrs',
  channel: 'text',
  mobile: '07700 900456',
  roleName: 'Duty manager',
  availableFrom: '08:00',
  availableTo: '20:00',
  ageMin: 18,
  ageMax: null,
  districts: ['DT4'],
  accepts: ['frailty'],
  excludes: [],
  reviewBy: '2031-01-31',
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/lead/services', () => {
  it('answers the services the lead may choose from, as id and name only', async () => {
    server.use(
      http.get(`${BACKEND_BASE}/HealthcareService`, () =>
        HttpResponse.json({
          resourceType: 'Bundle',
          type: 'searchset',
          total: 1,
          entry: [{ resource: { resourceType: 'HealthcareService', id: 's-1', name: 'Reablement', active: true, telecom: [{ value: '07700900456' }] } }],
        }),
      ),
    );
    const response = await GET(await request('GET', 'lead'));
    expect(response.status).toBe(200);
    const body = await response.text();
    expect(JSON.parse(body)).toEqual({ services: [{ id: 's-1', name: 'Reablement' }] });
    expect(body).not.toContain('07700900456');
  });

  it('answers 403 to an advisor', async () => {
    expect((await GET(await request('GET', 'advisor'))).status).toBe(403);
  });
});

describe('POST /api/bff/lead/services', () => {
  it('answers 403 without the CSRF header, even for a lead', async () => {
    const response = await POST(await request('POST', 'lead', { key: KEY, body: VALID_BODY }));
    expect(response.status).toBe(403);
  });

  it('answers 403 to an advisor', async () => {
    const response = await POST(await request('POST', 'advisor', { csrf: true, key: KEY, body: VALID_BODY }));
    expect(response.status).toBe(403);
  });

  it('answers 400 with no Idempotency-Key, and does not call the back end', async () => {
    let called = false;
    server.use(http.post(`${BACKEND_BASE}/HealthcareService/$setup`, () => { called = true; return HttpResponse.json({}, { status: 201 }); }));
    const response = await POST(await request('POST', 'lead', { csrf: true, body: VALID_BODY }));
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('answers 400 for a body with no name, and does not call the back end', async () => {
    let called = false;
    server.use(http.post(`${BACKEND_BASE}/HealthcareService/$setup`, () => { called = true; return HttpResponse.json({}, { status: 201 }); }));
    const rest: Record<string, unknown> = { ...VALID_BODY };
    delete rest.name;
    const response = await POST(await request('POST', 'lead', { csrf: true, key: KEY, body: rest }));
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('sends the body to $setup as Parameters with the key, and answers the new service id only', async () => {
    let forwarded: { body: unknown; key: string | null } | undefined;
    server.use(
      http.post(`${BACKEND_BASE}/HealthcareService/$setup`, async ({ request }) => {
        forwarded = { body: await request.json(), key: request.headers.get('idempotency-key') };
        return HttpResponse.json({ resourceType: 'HealthcareService', id: 's-new-1' }, { status: 201 });
      }),
    );
    const response = await POST(await request('POST', 'lead', { csrf: true, key: KEY, body: VALID_BODY }));
    expect(response.status).toBe(201);
    const text = await response.text();
    expect(JSON.parse(text)).toEqual({ serviceId: 's-new-1' });
    expect(text).not.toContain('07700');
    expect(forwarded?.key).toBe(KEY);
    const parameters = forwarded?.body as { resourceType: string; parameter: { name: string }[] };
    expect(parameters.resourceType).toBe('Parameters');
    const names = parameters.parameter.map((p) => p.name);
    expect(names).toEqual(expect.arrayContaining(['name', 'category', 'measure', 'channel', 'mobile', 'district', 'availableFrom', 'availableTo', 'reviewBy']));
  });
});
