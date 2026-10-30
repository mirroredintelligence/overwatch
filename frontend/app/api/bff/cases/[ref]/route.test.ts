// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ADVISOR_TOKEN, advisorRequest } from '@/test/advisor-session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { CASE_FULL } from '@/test/fixtures/backend-shapes';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET, PUT } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The case routes against the back end's real answers (routes_cases.py, case_mapping.py): the answer
// is the JSON the back end's own mapping wrote (test/fixtures/backend-shapes.ts).

const SR_URL = `${BACKEND_BASE}/ServiceRequest/case-1`;
const URL_ = 'https://app.test/api/bff/cases/case-1';
const KEY = 'save-key-0001';
const context = (ref: string) => ({ params: Promise.resolve({ ref }) });

type Seen = { method: string; ifMatch: string | null; key: string | null; token: string | null; body: unknown };
const seen: Seen[] = [];

beforeEach(() => {
  seen.length = 0;
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.get(SR_URL, ({ request }) => {
      seen.push({ method: 'GET', ifMatch: null, key: null, token: request.headers.get('authorization'), body: null });
      return HttpResponse.json(CASE_FULL, { headers: { ETag: 'W/"1"' } });
    }),
    http.put(SR_URL, async ({ request }) => {
      seen.push({
        method: 'PUT',
        ifMatch: request.headers.get('if-match'),
        key: request.headers.get('idempotency-key'),
        token: request.headers.get('authorization'),
        body: await request.json(),
      });
      return HttpResponse.json(CASE_FULL, { headers: { ETag: 'W/"1"' } });
    }),
  );
});

afterEach(() => vi.unstubAllEnvs());

const get = async (role: 'advisor' | 'reporter' | 'lead' | 'clinical' | null, ref = 'case-1') =>
  GET(await advisorRequest(`https://app.test/api/bff/cases/${ref}`, role), context(ref));

async function put(
  role: 'advisor' | 'reporter' | 'lead' | 'clinical',
  body: unknown,
  options: { ifMatch?: string | null; key?: string | null; csrf?: boolean } = {},
) {
  return PUT(
    await advisorRequest(URL_, role, {
      method: 'PUT',
      csrf: options.csrf ?? true,
      key: options.key === undefined ? KEY : options.key,
      ifMatch: options.ifMatch === undefined ? 'W/"1"' : options.ifMatch,
      body,
    }),
    context('case-1'),
  );
}

const VALID = {
  referrerType: 'ambulance-crew',
  ageBand: '80+',
  postcode: 'DT4 8XX',
  needs: ['fall-no-injury', 'frailty'],
  urgency: 'within-2-hrs',
  scores: [],
};

describe('GET /api/bff/cases/[ref] (W11)', () => {
  it('answers the case the back end holds in coded form, with its case number, open time and ETag', async () => {
    const response = await get('advisor');

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      id: 'case-1',
      reference: '4821',
      referrerType: 'ambulance-crew',
      ageBand: '80+',
      postcode: 'DT4',
      needs: ['fall-no-injury', 'frailty'],
      urgency: 'within-2-hrs',
      scores: [{ method: 'news2', value: 2 }],
      openedAt: '2026-10-30T14:00:00Z',
      closed: false,
      closedAt: null,
      outcome: null,
      etag: 'W/"1"',
    });
    expect(seen[0]?.token).toBe(`Bearer ${ADVISOR_TOKEN}`);
  });

  it.each(['reporter', 'lead', 'clinical'] as const)('answers 403 for a %s and reads nothing (DEC-860)', async (role) => {
    expect((await get(role)).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('answers 404 with the one not-found code when the back end does not know the case, so another tenant\'s id reads as an id nobody holds', async () => {
    server.use(http.get(SR_URL, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found' }] }, { status: 404 })));
    const unknown = await get('advisor');
    expect(unknown.status).toBe(404);
    expect(await unknown.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
  });

  it('answers a back-end refusal (403) on an id route as the same 404 (idScoped, DEC-130 item 7)', async () => {
    server.use(http.get(SR_URL, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'forbidden' }] }, { status: 403 })));
    const response = await get('advisor');
    expect(response.status).toBe(404);
    expect(await response.json()).toMatchObject({ code: 'not-found' });
  });

  it('refuses a reference that cannot be a case id, before any read', async () => {
    expect((await get('advisor', 'a%20b')).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('answers 502 when the back end answers something that is not a case', async () => {
    server.use(http.get(SR_URL, () => HttpResponse.json({ resourceType: 'Patient', id: 'x' })));
    expect((await get('advisor')).status).toBe(502);
  });

  it('is never cached', async () => {
    expect((await get('advisor')).headers.get('cache-control')).toBe('private, no-store');
  });
});

describe('PUT /api/bff/cases/[ref] (W11)', () => {
  it('maps the coded body to the ServiceRequest the back end reads, with If-Match, the key and the bearer token', async () => {
    const response = await put('advisor', VALID);

    expect(response.status).toBe(200);
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({ method: 'PUT', ifMatch: 'W/"1"', key: KEY, token: `Bearer ${ADVISOR_TOKEN}` });
    expect(seen[0]?.body).toMatchObject({
      resourceType: 'ServiceRequest',
      id: 'case-1',
      priority: 'urgent',
      reasonCode: [
        { coding: [{ system: 'https://diucs.example/CodeSystem/need-category', code: 'fall-no-injury' }] },
        { coding: [{ system: 'https://diucs.example/CodeSystem/need-category', code: 'frailty' }] },
      ],
    });
  });

  it('writes the urgency extension the back end reads, so planned is kept as planned (DEC-773)', async () => {
    await put('advisor', { ...VALID, urgency: 'planned' }, { key: 'save-key-0002' });

    const extensions = (seen[0]?.body as { extension: { url: string; valueCode?: string }[] }).extension;
    expect(extensions).toContainEqual({ url: 'https://diucs.example/StructureDefinition/urgency', valueCode: 'planned' });
    expect((seen[0]?.body as { priority: string }).priority).toBe('routine');
  });

  it('sends no postcode when the stored district is to stay, and none of the Patient address', async () => {
    const withoutPostcode = { ...VALID, postcode: undefined };
    const response = await put('advisor', withoutPostcode);

    expect(response.status).toBe(200);
    expect(JSON.stringify(seen[0]?.body)).not.toContain('postalCode');
  });

  it('refuses a save with no Idempotency-Key, before any back-end call: the back end requires one', async () => {
    const response = await put('advisor', VALID, { key: null });

    expect(response.status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('a 412 from the back end answers 412 with the conflict code', async () => {
    server.use(http.put(SR_URL, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 412 })));

    const response = await put('advisor', VALID);

    expect(response.status).toBe(412);
    expect(await response.json()).toMatchObject({ code: 'conflict' });
  });

  it('a 400 for recorded scores that cannot change is passed on as invalid, not as a server fault', async () => {
    server.use(
      http.put(SR_URL, () =>
        HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] }, { status: 400 }),
      ),
    );
    expect((await put('advisor', VALID)).status).toBe(400);
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
    ['a postcode that is only a district', { ...VALID, postcode: 'DT4' }],
    ['no needs', { ...VALID, needs: [] }],
  ])('refuses %s with 400 and calls nothing', async (_label, body) => {
    expect((await put('advisor', body)).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('drops any field it does not know, such as a name', async () => {
    await put('advisor', { ...VALID, patientName: 'Sample Patient' });

    expect(JSON.stringify(seen[0]?.body)).not.toContain('Sample Patient');
  });

  it('refuses a body that names a tenant with 400, and calls nothing (TEN-044)', async () => {
    expect((await put('advisor', { ...VALID, tenantId: 'tenant-b' })).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it.each(['reporter', 'lead', 'clinical'] as const)('refuses a %s with 403, and a missing CSRF header with 403', async (role) => {
    expect((await put(role, VALID)).status).toBe(403);
    expect((await put('advisor', VALID, { csrf: false })).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
