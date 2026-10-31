// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetProfileCache } from '@/lib/tenant/profile';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { BOARD_A } from '@/test/fixtures/board';
import { BOARD_BODY, OWN_ORGANISATION } from '@/test/fixtures/network';
import { BACKEND_BASE, resetSeenBoardRequests, seenBoardRequests, TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { requestAs } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// GET /api/bff/wall/board (TEN-072): what a wall screen shows. The back end says which board the screen
// shows (`GET /screens/me/board-scope`) and this answers both the setting and the board, so the screen
// never reads one for the scope of the other. It takes no input: no tenant, scope or network comes from
// the query, a header or a body, and the screen has no network id to give.

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = '/api/bff/wall/board';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  resetSeenBoardRequests();
  resetProfileCache();
});
afterEach(() => vi.unstubAllEnvs());

const ask = (role: Parameters<typeof requestAs>[1], path = URL_, headers: Record<string, string> = {}) =>
  requestAs(TENANTS.A, role, { path, headers, session: { sub: 'screen-1', backendToken: TOKEN_ORG_A } });

const scopeIs = (body: Record<string, unknown>) => http.get(`${ROOT}/screens/me/board-scope`, () => HttpResponse.json(body));
const NET_NOT_READ = http.get(`${ROOT}/screens/me/network-board`, () => {
  throw new Error('the network board must not be read');
});

describe('GET /api/bff/wall/board', () => {
  it('answers a screen on its own board with the setting and the organisation’s board', async () => {
    server.use(scopeIs({ boardScope: 'tenant', fallback: false, scopeVersion: 2 }), NET_NOT_READ);
    const response = await GET(await ask('wall'));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ scope: { boardScope: 'tenant', scopeVersion: 2, fallback: false, networkName: null }, board: BOARD_A });
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it('answers a screen on a network with the network’s name and its rows as a board, own rows marked', async () => {
    server.use(
      scopeIs({ boardScope: 'network', fallback: false, scopeVersion: 3, networkName: 'West Dorset system' }),
      http.get(`${ROOT}/screens/me/network-board`, () => HttpResponse.json(BOARD_BODY)),
    );
    const body = (await (await GET(await ask('wall'))).json()) as { scope: unknown; board: { entries: { serviceId: string; organisation: string; ownOrganisation: boolean; name: string }[] } };
    expect(body.scope).toEqual({ boardScope: 'network', scopeVersion: 3, fallback: false, networkName: 'West Dorset system' });
    expect(body.board.entries.map((entry) => entry.serviceId)).toEqual(BOARD_BODY.entries.map((entry) => entry.row_ref));
    expect(body.board.entries[0]).toMatchObject({ organisation: OWN_ORGANISATION, ownOrganisation: true });
    expect(body.board.entries[1]?.ownOrganisation).toBe(false);
    // The tenant's own board is not read for a screen that shows a network.
    expect(seenBoardRequests).toHaveLength(0);
  });

  it('answers a screen whose network closed to it with its own board and the fallback flag', async () => {
    server.use(scopeIs({ boardScope: 'tenant', fallback: true, fallbackReason: 'network-unavailable', scopeVersion: 4 }));
    const body = (await (await GET(await ask('wall'))).json()) as { scope: unknown; board: unknown };
    expect(body).toEqual({ scope: { boardScope: 'tenant', scopeVersion: 4, fallback: true, networkName: null }, board: BOARD_A });
    expect(JSON.stringify(body)).not.toContain('network-unavailable');
  });

  it('falls back to the own board when the network closes between the two reads (404 on the network board)', async () => {
    server.use(
      scopeIs({ boardScope: 'network', fallback: false, scopeVersion: 3, networkName: 'West Dorset system' }),
      http.get(`${ROOT}/screens/me/network-board`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'x' }] }, { status: 404 })),
    );
    const body = (await (await GET(await ask('wall'))).json()) as { scope: unknown; board: unknown };
    expect(body).toEqual({ scope: { boardScope: 'tenant', scopeVersion: 3, fallback: true, networkName: null }, board: BOARD_A });
  });

  it('keeps a failure of the network board other than a refusal as a failure, never as a fallback', async () => {
    server.use(
      scopeIs({ boardScope: 'network', fallback: false, scopeVersion: 3, networkName: 'West Dorset system' }),
      http.get(`${ROOT}/screens/me/network-board`, () => HttpResponse.json({}, { status: 503 })),
    );
    expect((await GET(await ask('wall'))).status).toBe(503);
  });

  it('answers a screen the back end refuses (a revoked one) with the refusal, so the wall goes back to pairing', async () => {
    server.use(http.get(`${ROOT}/screens/me/board-scope`, () => HttpResponse.json({}, { status: 404 })));
    expect((await GET(await ask('wall'))).status).toBe(404);
    server.use(http.get(`${ROOT}/screens/me/board-scope`, () => HttpResponse.json({}, { status: 401 })));
    expect((await GET(await ask('wall'))).status).toBe(401);
  });

  it('answers 502 for a setting or a network board it cannot read, never a guess', async () => {
    server.use(scopeIs({ boardScope: 'moon' }));
    expect((await GET(await ask('wall'))).status).toBe(502);
    server.use(
      scopeIs({ boardScope: 'network', fallback: false, scopeVersion: 1, networkName: 'x' }),
      http.get(`${ROOT}/screens/me/network-board`, () => HttpResponse.json({ nothing: true })),
    );
    expect((await GET(await ask('wall'))).status).toBe(502);
  });

  it('lets a person who reads the board (advisor, lead, exec) have the own board with the own setting, and asks the screen routes nothing', async () => {
    server.use(http.get(`${ROOT}/screens/me/board-scope`, () => {
      throw new Error('a person is not a screen');
    }));
    for (const role of ['advisor', 'lead', 'exec'] as const) {
      const body = (await (await GET(await ask(role))).json()) as { scope: { boardScope: string; fallback: boolean } };
      expect(body.scope).toMatchObject({ boardScope: 'tenant', fallback: false });
    }
  });

  it('is 401 with no session and 403 for a role that does not read the board', async () => {
    const none = await GET(new Request(`https://${TENANTS.A.host}${URL_}`, { headers: { Host: TENANTS.A.host } }));
    expect(none.status).toBe(401);
    for (const role of ['reporter', 'clinical', 'owner', 'support', 'audit'] as const) expect((await GET(await ask(role))).status, role).toBe(403);
  });

  it('refuses a request that names a tenant, a scope or a network, before it asks the back end anything', async () => {
    let asked = false;
    server.use(http.get(`${ROOT}/screens/me/board-scope`, () => ((asked = true), HttpResponse.json({}))));
    for (const path of [`${URL_}?tenant=x`, `${URL_}?scope=network`, `${URL_}?networkId=net-sample`, `${URL_}?network=n1`]) {
      expect((await GET(await ask('wall', path))).status, path).toBe(400);
    }
    expect((await GET(await ask('wall', URL_, { 'X-Network-Id': 'net-sample' }))).status).toBe(400);
    expect(asked).toBe(false);
  });
});
