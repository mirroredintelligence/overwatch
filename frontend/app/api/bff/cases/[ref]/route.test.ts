// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER, csrfTokenFor } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET, PUT } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = csrfTokenFor({ tenantId: 'trust-a', host: 'app.test', sub: 'advisor-1' }, 'N'.repeat(43));
const URL_ = 'https://app.test/api/bff/cases/4821';
const SR_URL = `${BACKEND_BASE}/ServiceRequest/4821`;

type Seen = { method: string; ifMatch: string | null; token: string | null; body: unknown };
const seen: Seen[] = [];

const SAVED_SR = {
  resourceType: 'ServiceRequest',
  id: '4821',
  status: 'active',
  intent: 'plan',
  subject: { reference: '#p' },
  contained: [
    {
      resourceType: 'Patient',
      id: 'p',
      address: [{ postalCode: 'DT4 8XX' }],
      extension: [{ url: 'https://diucs.example/StructureDefinition/age-band', valueCode: '80+' }],
    },
  ],
  extension: [{ url: 'https://diucs.example/StructureDefinition/referrer-type', valueCode: 'ambulance-crew' }],
  priority: 'urgent',
  reasonCode: [
    { coding: [{ system: 'https://diucs.example/CodeSystem/need-category', code: 'fall-no-injury' }] },
    { coding: [{ system: 'https://diucs.example/CodeSystem/need-category', code: 'frailty' }] },
  ],
};

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

async function cookies(role: Role | null): Promise<Record<string, string>> {
  const jar: Record<string, string> = { [CSRF_COOKIE]: CSRF };
  if (role !== null) jar[SESSION_COOKIE] = await sealSession(session(role));
  return jar;
}

const context = (ref: string) => ({ params: Promise.resolve({ ref }) });

async function get(role: Role | null, ref = '4821'): Promise<Response> {
  return GET(requestWithCookies(`https://app.test/api/bff/cases/${ref}`, await cookies(role)), context(ref));
}

async function put(
  role: Role | null,
  body: unknown,
  options: { ifMatch?: string | null; csrf?: string | null } = {},
): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (options.ifMatch !== null) headers['If-Match'] = options.ifMatch ?? 'W/"1"';
  if (options.csrf !== null) headers[CSRF_HEADER] = options.csrf ?? CSRF;
  const request = requestWithCookies(URL_, await cookies(role), {
    method: 'PUT',
    headers,
    body: JSON.stringify(body),
  });
  return PUT(request, context('4821'));
}

const VALID = {
  referrerType: 'ambulance-crew',
  ageBand: '80+',
  postcode: 'DT4 8XX',
  needs: ['fall-no-injury', 'frailty'],
  urgency: 'within-2-hrs',
  scores: [],
};

beforeEach(() => {
  seen.length = 0;
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.get(SR_URL, ({ request }) => {
      seen.push({ method: 'GET', ifMatch: null, token: request.headers.get('authorization'), body: null });
      return HttpResponse.json(SAVED_SR, { headers: { ETag: 'W/"1"' } });
    }),
    http.put(SR_URL, async ({ request }) => {
      seen.push({
        method: 'PUT',
        ifMatch: request.headers.get('if-match'),
        token: request.headers.get('authorization'),
        body: await request.json(),
      });
      return HttpResponse.json(SAVED_SR, { headers: { ETag: 'W/"1"' } });
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/cases/[ref] (W11)', () => {
  it('answers the case in coded form with its ETag, and no patient detail beyond the district and age band', async () => {
    const response = await get('advisor');

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      id: '4821',
      referrerType: 'ambulance-crew',
      ageBand: '80+',
      postcode: 'DT4 8XX',
      needs: ['fall-no-injury', 'frailty'],
      urgency: 'within-2-hrs',
      scores: [],
      openedAt: null,
      etag: 'W/"1"',
    });
    expect(seen[0].token).toBe('Bearer token-for-advisor');
  });

  it('answers 403 for a reporter and reads nothing', async () => {
    expect((await get('reporter')).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('refuses a reference that cannot be a case id, before any read', async () => {
    expect((await get('advisor', 'a%20b')).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('is never cached', async () => {
    expect((await get('advisor')).headers.get('cache-control')).toBe('private, no-store');
  });
});

describe('PUT /api/bff/cases/[ref] (W11)', () => {
  it('maps the coded body to a ServiceRequest with If-Match and the bearer token', async () => {
    const response = await put('advisor', VALID);

    expect(response.status).toBe(200);
    expect(seen).toHaveLength(1);
    expect(seen[0].method).toBe('PUT');
    expect(seen[0].ifMatch).toBe('W/"1"');
    expect(seen[0].token).toBe('Bearer token-for-advisor');
    expect(seen[0].body).toMatchObject({
      resourceType: 'ServiceRequest',
      id: '4821',
      priority: 'urgent',
      reasonCode: [
        { coding: [{ system: 'https://diucs.example/CodeSystem/need-category', code: 'fall-no-injury' }] },
        { coding: [{ system: 'https://diucs.example/CodeSystem/need-category', code: 'frailty' }] },
      ],
    });
  });

  it('maps today and planned to routine, the back end having no planned priority (DEC-397)', async () => {
    await put('advisor', { ...VALID, urgency: 'today' });
    await put('advisor', { ...VALID, urgency: 'planned' });

    expect(seen.map((s) => (s.body as { priority: string }).priority)).toEqual(['routine', 'routine']);
  });

  it('a 412 from the back end answers 412 with the conflict code', async () => {
    server.use(http.put(SR_URL, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 412 })));

    const response = await put('advisor', VALID);

    expect(response.status).toBe(412);
    expect(await response.json()).toMatchObject({ code: 'conflict' });
  });

  it('refuses a save with no If-Match, before any back-end call', async () => {
    const response = await put('advisor', VALID, { ifMatch: null });

    expect(response.status).toBe(428);
    expect(seen).toHaveLength(0);
  });

  it.each([
    ['an age outside the bands', { ...VALID, ageBand: '81' }],
    ['a need outside the list', { ...VALID, needs: ['fall'] }],
    ['a referrer outside the list', { ...VALID, referrerType: 'friend' }],
    ['a postcode that is not full', { ...VALID, postcode: 'DT4 8X' }],
    ['no needs', { ...VALID, needs: [] }],
  ])('refuses %s with 400 and calls nothing', async (_label, body) => {
    expect((await put('advisor', body)).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('drops any field it does not know, such as a name', async () => {
    await put('advisor', { ...VALID, patientName: 'Sample Patient' });

    expect(JSON.stringify(seen[0].body)).not.toContain('Sample Patient');
  });

  it('refuses a body that names a tenant with 400, and calls nothing (TEN-044)', async () => {
    expect((await put('advisor', { ...VALID, tenantId: 'tenant-b' })).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('refuses a reporter with 403 and a missing CSRF header with 403', async () => {
    expect((await put('reporter', VALID)).status).toBe(403);
    expect((await put('advisor', VALID, { csrf: null })).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
