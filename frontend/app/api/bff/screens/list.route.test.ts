// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

// GET /api/bff/screens: the lead's list of wall screens (W9I, TEN-072). The back end's answer is
// GET /screens (routes_screens.py): `{scope, asOf, screens: [...]}`, never a token, hash or secret.

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/screens';
const ROW = {
  deviceId: 's-1',
  name: 'Ward 4 corridor',
  location: 'Level 2',
  status: 'online',
  boardScope: 'tenant',
  pairedAt: '2026-10-27T10:00:00Z',
  lastSeenAt: '2026-10-30T09:59:20Z',
  revokedAt: null,
};
const ANSWER = { scope: 'tenant', asOf: '2026-10-30T10:00:00Z', screens: [ROW] };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});
afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/screens', () => {
  it('is 401 with no session and 403 for every role but lead', async () => {
    expect((await GET(await leadRequest(URL_, null))).status).toBe(401);
    for (const role of ['advisor', 'clinical', 'owner', 'exec', 'wall', 'reporter', 'support', 'audit'] as const) {
      expect((await GET(await leadRequest(URL_, role))).status, role).toBe(403);
    }
  });

  it('passes the lead the list the back end gave, with the lead’s own token', async () => {
    let seen: { auth: string | null; url: string } | undefined;
    server.use(
      http.get(`${ROOT}/screens`, ({ request }) => {
        seen = { auth: request.headers.get('authorization'), url: request.url };
        return HttpResponse.json(ANSWER);
      }),
    );
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(ANSWER);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(seen?.auth).toBe('Bearer token-for-the-lead');
    expect(new URL(seen!.url).search).toBe('');
  });

  it('never passes on a field the page does not know, such as a hash the back end sent by mistake', async () => {
    server.use(http.get(`${ROOT}/screens`, () => HttpResponse.json({ ...ANSWER, screens: [{ ...ROW, tokenHash: 'a'.repeat(64) }] })));
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(await response.text()).not.toContain('tokenHash');
  });

  it('answers an empty list when the back end has none, and an error, never an empty list, for a malformed answer', async () => {
    server.use(http.get(`${ROOT}/screens`, () => HttpResponse.json({ ...ANSWER, screens: [] })));
    expect((await (await GET(await leadRequest(URL_, 'lead'))).json()).screens).toEqual([]);
    server.use(http.get(`${ROOT}/screens`, () => HttpResponse.json({ nothing: true })));
    expect((await GET(await leadRequest(URL_, 'lead'))).status).toBe(500);
  });

  it('keeps the back end’s 503 when it is down', async () => {
    server.use(http.get(`${ROOT}/screens`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'transient', diagnostics: 'x' }] }, { status: 503 })));
    expect((await GET(await leadRequest(URL_, 'lead'))).status).toBe(503);
  });

  it('ends the session when the back end no longer knows it (401)', async () => {
    server.use(http.get(`${ROOT}/screens`, () => HttpResponse.json({}, { status: 401 })));
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ code: 'session-ended' });
  });
});
