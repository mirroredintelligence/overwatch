// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET, PUT } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/lead/services/svc-ucr-west/coverage';
const ctx = { params: Promise.resolve({ id: 'svc-ucr-west' }) };
const KEY = 'coverage-key-0001';

const FORM = {
  service: { id: 'svc-ucr-west', name: 'UCR West' },
  available: ['DT1', 'DT2', 'DT3', 'DT4'],
  districts: ['DT3', 'DT4'],
  responseHours: 2,
  days: ['mon', 'tue'],
  others: [{ district: 'DT4', service: 'UCR East' }],
};
const SAVE = { districts: ['DT3', 'DT4'], responseHours: 2, days: ['mon', 'tue'] };

type Seen = { method: string; body: unknown; key: string | null; auth: string | null };
let seen: Seen[];

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  seen = [];
  const record = async (request: Request): Promise<Response> => {
    const text = await request.text();
    seen.push({ method: request.method, body: text === '' ? null : (JSON.parse(text) as unknown), key: request.headers.get('idempotency-key'), auth: request.headers.get('authorization') });
    return HttpResponse.json(FORM);
  };
  server.use(
    http.get(`${ROOT}/lead/services/svc-ucr-west/coverage`, ({ request }) => record(request)),
    http.put(`${ROOT}/lead/services/svc-ucr-west/coverage`, ({ request }) => record(request)),
  );
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/services/[id]/coverage', () => {
  it('reads the coverage area with the lead’s token and answers the form as read', async () => {
    const response = await GET(await leadRequest(URL_, 'lead'), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(FORM);
    expect(seen[0].auth).toMatch(/^Bearer /);
  });

  it('is for a lead only', async () => {
    for (const role of ['advisor', 'exec', 'owner'] as const) expect((await GET(await leadRequest(URL_, role), ctx)).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('answers 404, with no call, for an id that is not shaped like a service id', async () => {
    const response = await GET(await leadRequest(URL_, 'lead'), { params: Promise.resolve({ id: '../x' }) });
    expect(response.status).toBe(404);
    expect(seen).toHaveLength(0);
  });

  it('answers 502 when the back end’s answer is not a coverage area, never a guess', async () => {
    server.use(http.get(`${ROOT}/lead/services/svc-ucr-west/coverage`, () => HttpResponse.json({ service: 'x' })));
    expect((await GET(await leadRequest(URL_, 'lead'), ctx)).status).toBe(502);
  });

  it('answers the back end’s 404 as a 404 (the route is not built there yet)', async () => {
    server.use(http.get(`${ROOT}/lead/services/svc-ucr-west/coverage`, () => new HttpResponse(null, { status: 404 })));
    expect((await GET(await leadRequest(URL_, 'lead'), ctx)).status).toBe(404);
  });
});

describe('PUT /api/bff/lead/services/[id]/coverage', () => {
  const put = async (body: unknown, options: { csrf?: boolean; key?: string | null } = {}) =>
    PUT(await leadRequest(URL_, 'lead', { method: 'PUT', csrf: options.csrf ?? true, key: options.key === undefined ? KEY : options.key, body }), ctx);

  it('sends the three answers and the key to the back end and answers the saved form', async () => {
    const response = await put({ ...SAVE, districts: ['DT3', 'DT4', 'DT3'] });
    expect(response.status).toBe(200);
    expect(seen).toEqual([{ method: 'PUT', body: SAVE, key: KEY, auth: expect.stringMatching(/^Bearer /) }]);
    expect(((await response.json()) as { service: { name: string } }).service.name).toBe('UCR West');
  });

  it('answers 403 without the CSRF header, 400 without a key, and calls nothing', async () => {
    expect((await put(SAVE, { csrf: false })).status).toBe(403);
    expect((await put(SAVE, { key: null })).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('is for a lead only', async () => {
    const response = await PUT(await leadRequest(URL_, 'advisor', { method: 'PUT', csrf: true, key: KEY, body: SAVE }), ctx);
    expect(response.status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it.each([
    ['no districts', { ...SAVE, districts: [] }],
    ['a district that is not one', { ...SAVE, districts: ['dt3'] }],
    ['a response target that is not whole hours', { ...SAVE, responseHours: 1.5 }],
    ['a response target over the limit', { ...SAVE, responseHours: 73 }],
    ['no days', { ...SAVE, days: [] }],
    ['a day that is not a day', { ...SAVE, days: ['funday'] }],
    ['a body that is not an object', 'text'],
  ])('answers 400 for %s, and does not call the back end', async (_name, body) => {
    expect((await put(body)).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('refuses a body that names a tenant or a network, whatever else it holds', async () => {
    expect((await put({ ...SAVE, tenantId: 't-2' })).status).toBeGreaterThanOrEqual(400);
    expect(seen).toHaveLength(0);
  });
});
