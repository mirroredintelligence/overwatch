// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { PUT } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

// PUT /api/bff/screens/[id]/board-scope: which board a wall screen shows (TEN-072, W9B's
// PUT /screens/{deviceId}/board-scope). The lead (or the tenant administrator) chooses between the
// organisation's own board and a network the server offered in the list. The network id is the ONE body
// key this BFF lets through (`allowNetworkIdInBody`); If-Match and the Idempotency-Key are passed on.

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/screens/s-1/board-scope';
const context = (id = 's-1') => ({ params: Promise.resolve({ id }) });
const ANSWER = { deviceId: 's-1', name: 'Ward 4 corridor', location: 'Level 2', status: 'active', boardScope: 'network', networkId: 'net-west', networkName: 'West Dorset system', networkAvailable: true, scopeVersion: 2 };
const put = (body: unknown, options: { role?: 'lead' | 'tenant-admin' | 'advisor'; ifMatch?: string | null; key?: string | null; csrf?: boolean } = {}) =>
  leadRequest(URL_, options.role ?? 'lead', { method: 'PUT', csrf: options.csrf ?? true, key: options.key === undefined ? 'board-key-1' : options.key, body }).then((request) => {
    const headers = new Headers(request.headers);
    if (options.ifMatch !== null) headers.set('If-Match', options.ifMatch ?? 'W/"1"');
    return new Request(request, { headers });
  });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});
afterEach(() => vi.unstubAllEnvs());

describe('PUT /api/bff/screens/[id]/board-scope', () => {
  it('is 401 with no session, 403 for any role but lead and tenant administrator, and 403 without the CSRF token', async () => {
    expect((await PUT(await leadRequest(URL_, null, { method: 'PUT' }), context())).status).toBe(401);
    for (const role of ['advisor', 'clinical', 'owner', 'exec', 'wall', 'reporter', 'support', 'audit'] as const) {
      expect((await PUT(await put({ boardScope: 'tenant' }, { role: role as 'advisor' }), context())).status, role).toBe(403);
    }
    const noCsrf = await PUT(await put({ boardScope: 'tenant' }, { csrf: false }), context());
    expect(noCsrf.status).toBe(403);
    expect(await noCsrf.json()).toMatchObject({ code: 'csrf' });
  });

  it('sends the choice with the lead’s token, If-Match and the same key, and answers the setting as it is now', async () => {
    let seen: { auth: string | null; match: string | null; key: string | null; body: unknown; path: string; method: string } | undefined;
    server.use(
      http.put(`${ROOT}/screens/s-1/board-scope`, async ({ request }) => {
        seen = {
          auth: request.headers.get('authorization'),
          match: request.headers.get('if-match'),
          key: request.headers.get('idempotency-key'),
          body: await request.json(),
          path: new URL(request.url).pathname,
          method: request.method,
        };
        return HttpResponse.json(ANSWER, { headers: { ETag: 'W/"2"' } });
      }),
    );
    const response = await PUT(await put({ boardScope: 'network', networkId: 'net-west' }), context());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ deviceId: 's-1', boardScope: 'network', networkId: 'net-west', networkName: 'West Dorset system', networkAvailable: true, scopeVersion: 2 });
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(seen).toMatchObject({ auth: 'Bearer token-for-the-lead', match: 'W/"1"', key: 'board-key-1', body: { boardScope: 'network', networkId: 'net-west' }, path: '/screens/s-1/board-scope', method: 'PUT' });
  });

  it('lets the tenant administrator change a screen’s board', async () => {
    server.use(http.put(`${ROOT}/screens/s-1/board-scope`, () => HttpResponse.json({ ...ANSWER, boardScope: 'tenant', networkId: null, networkName: null })));
    expect((await PUT(await put({ boardScope: 'tenant' }, { role: 'tenant-admin' }), context())).status).toBe(200);
  });

  it('forwards only the two fields it knows', async () => {
    let body: unknown;
    server.use(http.put(`${ROOT}/screens/s-1/board-scope`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ ...ANSWER, boardScope: 'tenant', networkId: null, networkName: null });
    }));
    await PUT(await put({ boardScope: 'tenant', extra: 'x', networkId: undefined }), context());
    expect(body).toEqual({ boardScope: 'tenant' });
  });

  it.each([
    ['a tenant named in the body', { boardScope: 'tenant', tenantId: 'trust-b' }],
    ['a scope key', { boardScope: 'tenant', scope: 'network' }],
    ['a nested network id', { boardScope: 'network', choice: { networkId: 'net-west' } }],
    ['a network id that is not one', { boardScope: 'network', networkId: 'trust-b' }],
    ['another network key', { boardScope: 'network', networkId: 'net-west', networkIds: ['net-a'] }],
  ])('refuses %s before any work (400)', async (_name, body) => {
    let called = false;
    server.use(http.put(`${ROOT}/screens/s-1/board-scope`, () => {
      called = true;
      return HttpResponse.json(ANSWER);
    }));
    const response = await PUT(await put(body), context());
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it.each([
    ['an unknown board', { boardScope: 'moon' }],
    ['a network board with no network', { boardScope: 'network' }],
    ['an own board with a network', { boardScope: 'tenant', networkId: 'net-west' }],
    ['no board', {}],
    ['a body that is not an object', ['network']],
  ])('refuses %s (400) without calling the back end', async (_name, body) => {
    let called = false;
    server.use(http.put(`${ROOT}/screens/s-1/board-scope`, () => {
      called = true;
      return HttpResponse.json(ANSWER);
    }));
    const response = await PUT(await put(body), context());
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('refuses a missing or malformed If-Match or Idempotency-Key (400), and the network id in the query', async () => {
    expect((await PUT(await put({ boardScope: 'tenant' }, { ifMatch: null }), context())).status).toBe(400);
    expect((await PUT(await put({ boardScope: 'tenant' }, { ifMatch: '1' }), context())).status).toBe(400);
    expect((await PUT(await put({ boardScope: 'tenant' }, { key: null }), context())).status).toBe(400);
    const queried = await leadRequest(`${URL_}?networkId=net-west`, 'lead', { method: 'PUT', csrf: true, key: 'k', body: { boardScope: 'tenant' } });
    expect((await PUT(queried, context())).status).toBe(400);
  });

  it('answers a malformed id as the one 404 without calling the back end', async () => {
    const response = await PUT(await put({ boardScope: 'tenant' }), context('../x'));
    expect(response.status).toBe(404);
  });

  it.each([
    [404, 'not-found'],
    [412, 'invalid'],
    [428, 'invalid'],
    [503, 'transient'],
  ])('keeps the back end’s %s', async (status, code) => {
    server.use(http.put(`${ROOT}/screens/s-1/board-scope`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code, diagnostics: 'x' }] }, { status })));
    expect((await PUT(await put({ boardScope: 'tenant' }), context())).status).toBe(status);
  });

  it('ends the session when the back end no longer knows it (401), and refuses a malformed answer (never passes it on)', async () => {
    server.use(http.put(`${ROOT}/screens/s-1/board-scope`, () => HttpResponse.json({}, { status: 401 })));
    expect(await (await PUT(await put({ boardScope: 'tenant' }), context())).json()).toMatchObject({ code: 'session-ended' });
    server.use(http.put(`${ROOT}/screens/s-1/board-scope`, () => HttpResponse.json({ nothing: true })));
    expect((await PUT(await put({ boardScope: 'tenant' }), context())).status).toBe(500);
  });
});
