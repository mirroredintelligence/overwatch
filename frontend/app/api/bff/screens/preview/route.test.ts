// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { TENANTS } from '@/test/tenants';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { PROFILE_URL } from '@/test/msw/handlers/profile';
import { server } from '@/test/msw/server';
import { resetProfileCache } from '@/lib/tenant/profile';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

// POST /api/bff/screens/preview: the confirm step of pairing (TEN-072, docs/design/network-ui.md section
// 6, ScreenClaim). The lead types the code and is told which organisation the screen will show and when
// the screen first asked. The back end's `POST /screens/preview` answers `{firstSeenAt, deviceClass}`; the
// organisation's name is the tenant's own, from its profile (the same read the wall's heading uses).

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/screens/preview';
const ANSWER = { firstSeenAt: '2026-10-30T09:56:00Z', deviceClass: 'wall-display' };
const ask = (body: unknown, options: { role?: 'lead' | 'advisor'; csrf?: boolean } = {}) =>
  leadRequest(URL_, options.role ?? 'lead', { method: 'POST', csrf: options.csrf ?? true, body });

beforeEach(() => {
  resetProfileCache();
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/screens/preview', () => {
  it('is 401 with no session, 403 for every role but lead, 403 without the CSRF token', async () => {
    expect((await POST(await leadRequest(URL_, null, { method: 'POST' }))).status).toBe(401);
    for (const role of ['advisor', 'clinical', 'owner', 'exec', 'wall', 'reporter', 'support', 'audit', 'tenant-admin'] as const) {
      expect((await POST(await leadRequest(URL_, role, { method: 'POST', csrf: true, body: { code: '123456' } }))).status, role).toBe(403);
    }
    expect((await POST(await ask({ code: '123456' }, { csrf: false }))).status).toBe(403);
  });

  it('asks the back end with the lead’s token and the code, and answers the organisation, the time and the kind', async () => {
    let seen: { auth: string | null; body: unknown; path: string } | undefined;
    server.use(
      http.post(`${ROOT}/screens/preview`, async ({ request }) => {
        seen = { auth: request.headers.get('authorization'), body: await request.json(), path: new URL(request.url).pathname };
        return HttpResponse.json(ANSWER);
      }),
    );
    const response = await POST(await ask({ code: '482 913' }));
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toEqual({ organisationName: TENANTS.A.profile?.displayName, firstSeenAt: ANSWER.firstSeenAt, deviceClass: 'wall-display' });
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(seen).toMatchObject({ auth: 'Bearer token-for-the-lead', body: { code: '482913' }, path: '/screens/preview' });
  });

  it('answers a null organisation name, not a failure, when the profile cannot be read', async () => {
    server.use(
      http.post(`${ROOT}/screens/preview`, () => HttpResponse.json(ANSWER)),
      http.get(PROFILE_URL, () => HttpResponse.json({}, { status: 503 })),
    );
    const response = await POST(await ask({ code: '482913' }));
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ organisationName: null });
  });

  it('refuses a body that is not a six-digit code, a body that names a tenant, and an unknown field, without calling the back end', async () => {
    let called = false;
    server.use(http.post(`${ROOT}/screens/preview`, () => {
      called = true;
      return HttpResponse.json(ANSWER);
    }));
    for (const body of [{}, { code: '12' }, { code: 12345678 }, { code: '123456', tenantId: 'x' }, { code: '123456', extra: 1 }, [], 'x']) {
      expect((await POST(await ask(body))).status, JSON.stringify(body)).toBe(400);
    }
    expect(called).toBe(false);
  });

  it('answers a refused code as the one not-found of pairing, a limit as 429 and a failure as 503', async () => {
    server.use(http.post(`${ROOT}/screens/preview`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'x' }] }, { status: 404 })));
    const refused = await POST(await ask({ code: '123456' }));
    expect(refused.status).toBe(404);
    expect(await refused.json()).toMatchObject({ code: 'not-found', message: 'That code is not valid or has expired. Check the screen for a new code.' });
    server.use(http.post(`${ROOT}/screens/preview`, () => HttpResponse.json({}, { status: 429, headers: { 'Retry-After': '300' } })));
    const limited = await POST(await ask({ code: '123456' }));
    expect(limited.status).toBe(429);
    server.use(http.post(`${ROOT}/screens/preview`, () => HttpResponse.json({}, { status: 500 })));
    expect((await POST(await ask({ code: '123456' }))).status).toBe(503);
  });

  it('refuses a back-end answer that is not the one expected', async () => {
    server.use(http.post(`${ROOT}/screens/preview`, () => HttpResponse.json({ firstSeenAt: 'yesterday', deviceClass: 'wall-display' })));
    expect((await POST(await ask({ code: '123456' }))).status).toBe(503);
  });
});
