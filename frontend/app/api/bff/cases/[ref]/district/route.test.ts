// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ADVISOR_TOKEN, advisorRequest } from '@/test/advisor-session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { CASE_FULL } from '@/test/fixtures/backend-shapes';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { PUT } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// Choosing a district (W50, W9H DEC-1045): the advisor picks one of the chips the options screen offered
// when the postcode was not found or is outside the area. The BFF reads the case for its ETag, then saves
// the district on its own (the extension on the contained Patient, the back end's `postcode-district`),
// with the ETag and a key. Only a district is taken: no postcode, no tenant, nothing else.

const SR_URL = `${BACKEND_BASE}/ServiceRequest/case-1`;
const URL_ = 'https://app.test/api/bff/cases/case-1/district';
const KEY = 'district-key-0001';
const EXTENSION = 'https://diucs.example/StructureDefinition/postcode-district';
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
      return HttpResponse.json(CASE_FULL, { headers: { ETag: 'W/"3"' } });
    }),
    http.put(SR_URL, async ({ request }) => {
      seen.push({ method: 'PUT', ifMatch: request.headers.get('if-match'), key: request.headers.get('idempotency-key'), token: request.headers.get('authorization'), body: await request.json() });
      return HttpResponse.json(CASE_FULL, { headers: { ETag: 'W/"4"' } });
    }),
  );
});
afterEach(() => vi.unstubAllEnvs());

type Options = { key?: string | null; csrf?: boolean; ref?: string };
async function choose(role: 'advisor' | 'clinical' | 'lead' | 'reporter' | 'exec' | null, body: unknown, options: Options = {}) {
  const ref = options.ref ?? 'case-1';
  return PUT(
    await advisorRequest(`https://app.test/api/bff/cases/${ref}/district`, role, {
      method: 'PUT',
      body,
      key: options.key === undefined ? KEY : options.key,
      csrf: options.csrf ?? true,
    }),
    context(ref),
  );
}

describe('PUT /api/bff/cases/[ref]/district', () => {
  it('reads the case for its ETag, then saves the district on its own with the ETag, a key and the advisor’s token', async () => {
    const response = await choose('advisor', { district: 'DT1' });

    expect(response.status).toBe(200);
    expect(seen.map((s) => s.method)).toEqual(['GET', 'PUT']);
    const saved = seen[1]!;
    expect(saved).toMatchObject({ ifMatch: 'W/"3"', key: KEY, token: `Bearer ${ADVISOR_TOKEN}` });
    expect(saved.body).toEqual({
      resourceType: 'ServiceRequest',
      contained: [{ resourceType: 'Patient', id: 'p', extension: [{ url: EXTENSION, valueCode: 'DT1' }] }],
    });
    expect(JSON.stringify(saved.body)).not.toContain('postalCode');
  });

  it('answers the case as the back end now holds it', async () => {
    const view = (await (await choose('advisor', { district: 'BH21' })).json()) as { id?: unknown };
    expect(view.id).toBe(CASE_FULL.id);
  });

  it.each(['DT4 8XX', 'dt4', 'DT48X9', '', 'DT 4', 7, null, undefined])('refuses %j as a district, 400, before the back end', async (district) => {
    expect((await choose('advisor', { district })).status).toBe(400);
    expect(seen).toEqual([]);
  });

  it.each([{ district: 'DT1', postcode: 'DT4 8XX' }, { district: 'DT1', tenant: 'trust-b' }, { district: 'DT1', ifMatch: 'x' }])('refuses a body that holds more than the district (%j)', async (body) => {
    expect((await choose('advisor', body)).status).toBe(400);
    expect(seen).toEqual([]);
  });

  it('needs the key the screen made for this press', async () => {
    expect((await choose('advisor', { district: 'DT1' }, { key: null })).status).toBe(400);
    expect(seen).toEqual([]);
  });

  it('refuses a case id that is not one, before the back end', async () => {
    expect((await choose('advisor', { district: 'DT1' }, { ref: 'a b' })).status).toBe(400);
    expect(seen).toEqual([]);
  });

  it('answers 412 conflict when the case changed between the read and the save', async () => {
    server.use(http.put(SR_URL, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict' }] }, { status: 412 })));
    const response = await choose('advisor', { district: 'DT1' });
    expect(response.status).toBe(412);
    expect(await response.json()).toEqual({ code: 'conflict' });
  });

  it('answers a district the back end refuses as 400, and another tenant’s or an unknown case as the one 404', async () => {
    server.use(http.put(SR_URL, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] }, { status: 400 })));
    expect((await choose('advisor', { district: 'DT1' })).status).toBe(400);
    server.use(http.get(SR_URL, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found' }] }, { status: 404 })));
    expect((await choose('advisor', { district: 'DT1' })).status).toBe(404);
  });

  it('is for the advisor only, as every advisor route is (DEC-860): every other role, and no session, is refused before the back end', async () => {
    for (const role of ['lead', 'reporter', 'exec', 'clinical'] as const) expect((await choose(role, { district: 'DT1' })).status, role).toBe(403);
    expect((await choose(null, { district: 'DT1' })).status).toBe(401);
    expect((await choose('advisor', { district: 'DT1' }, { csrf: false })).status).toBe(403);
    expect(seen).toEqual([]);
  });
});
