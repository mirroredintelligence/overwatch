// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

// POST /api/bff/screens/[id]/revoke: a shift lead disconnects a wall screen (W9I, TEN-072). The back
// end's route is POST /screens/{id}/revoke, which answers 200 `{deviceId, status: 'revoked',
// revokedAt}` and needs a JSON body and an Idempotency-Key.

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/screens/s-1/revoke';
const ANSWER = { deviceId: 's-1', status: 'revoked', revokedAt: '2026-10-30T10:00:00Z' };
const context = (id = 's-1') => ({ params: Promise.resolve({ id }) });
const asLead = (options: Parameters<typeof leadRequest>[2] = {}) =>
  leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: 'rev-key-1', ...options });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/screens/[id]/revoke', () => {
  it('is 401 with no session, 403 for every role but lead, and 403 without the CSRF token', async () => {
    expect((await POST(await leadRequest(URL_, null, { method: 'POST' }), context())).status).toBe(401);
    for (const role of ['advisor', 'clinical', 'owner', 'exec', 'wall', 'reporter', 'support', 'audit'] as const) {
      const response = await POST(await leadRequest(URL_, role, { method: 'POST', csrf: true, key: 'k' }), context());
      expect(response.status, role).toBe(403);
    }
    const noCsrf = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: false, key: 'k' }), context());
    expect(noCsrf.status).toBe(403);
    expect(await noCsrf.json()).toMatchObject({ code: 'csrf' });
  });

  it('revokes the screen with the lead’s token, the same key and an empty JSON body, and answers the new state', async () => {
    let seen: { auth: string | null; key: string | null; type: string | null; body: unknown; path: string } | undefined;
    server.use(
      http.post(`${ROOT}/screens/s-1/revoke`, async ({ request }) => {
        seen = {
          auth: request.headers.get('authorization'),
          key: request.headers.get('idempotency-key'),
          type: request.headers.get('content-type'),
          body: await request.json(),
          path: new URL(request.url).pathname,
        };
        return HttpResponse.json(ANSWER);
      }),
    );
    const response = await POST(await asLead(), context());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(ANSWER);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(seen).toMatchObject({ auth: 'Bearer token-for-the-lead', key: 'rev-key-1', body: {}, path: '/screens/s-1/revoke' });
    expect(seen?.type).toMatch(/json/);
  });

  it('needs an Idempotency-Key and calls nothing without one', async () => {
    let called = false;
    server.use(http.post(`${ROOT}/screens/s-1/revoke`, () => { called = true; return HttpResponse.json(ANSWER); }));
    const response = await POST(await asLead({ key: null }), context());
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('never sends an id that is not an id to the back end: it is the one 404', async () => {
    let called = false;
    server.use(http.post(`${ROOT}/screens/:id/revoke`, () => { called = true; return HttpResponse.json(ANSWER); }));
    for (const id of ['../x', 'a b', '', 'x'.repeat(65)]) {
      expect((await POST(await asLead(), context(id))).status, id).toBe(404);
    }
    expect(called).toBe(false);
  });

  it('answers the one 404 for a screen the back end does not hold, whichever tenant it is in', async () => {
    server.use(http.post(`${ROOT}/screens/s-1/revoke`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'x' }] }, { status: 404 })));
    expect((await POST(await asLead(), context())).status).toBe(404);
  });

  it('refuses a body that names a tenant before it calls the back end', async () => {
    let called = false;
    server.use(http.post(`${ROOT}/screens/:id/revoke`, () => { called = true; return HttpResponse.json(ANSWER); }));
    const response = await POST(await asLead({ body: { tenant: 'other' } }), context());
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('is an error, not a success, when the back end answers something that is not a revoke', async () => {
    server.use(http.post(`${ROOT}/screens/s-1/revoke`, () => HttpResponse.json({ deviceId: 's-1', status: 'online' })));
    expect((await POST(await asLead(), context())).status).toBe(500);
  });
});
