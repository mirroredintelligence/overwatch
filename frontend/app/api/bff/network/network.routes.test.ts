// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROLES, type Role } from '@/lib/auth/session';
import { BOARD_BODY, boardEntry, OWN_ORGANISATION } from '@/test/fixtures/network';
import { NETWORK_ID, networkRequest } from '@/test/network';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { NETWORK_ROOT, networkHandlers, resetNetworkBackend, seenNetwork } from '@/test/msw/handlers/network';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { GET as getBoard } from './board/route';
import { GET as getCriteria } from './criteria/route';
import { GET as getDirectory } from './directory/route';
import { GET as getList } from './route';
import { GET as getPhones } from './phones/route';
import { GET as getSystemNow } from './system-now/route';
import { GET as getWeek } from './week/route';

// TEN-068: the BFF's network routes. Each one: the session's tenant only, the network named by the
// `networkId` the server offered, the availability asked of the back end on every call, a body rebuilt
// from the fields the page uses, and one refusal for every reason a network is not available.

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

type Handler = (request: Request, context?: unknown) => Promise<Response>;

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${NETWORK_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetNetworkBackend();
  server.use(...networkHandlers);
});
afterEach(() => vi.unstubAllEnvs());

const A = TENANTS.A;
const VIEW_ROLES: Role[] = ['advisor', 'clinical', 'lead', 'owner', 'exec'];
const call = (handler: Handler, request: Request) => handler(request, undefined);
const networkCalls = () => seenNetwork.filter((c) => c.path.startsWith('/network/'));

const READS: [string, Handler, string, string][] = [
  ['board', getBoard as Handler, '/board', '/network/net-sample/board'],
  ['directory', getDirectory as Handler, '/directory', '/network/net-sample/directory'],
  ['criteria', getCriteria as Handler, '/criteria', '/network/net-sample/criteria'],
  ['system-now', getSystemNow as Handler, '/system-now', '/network/net-sample/system-now'],
  ['phones', getPhones as Handler, '/phones', '/network/net-sample/phones'],
];

describe('GET /api/bff/network (the networks this session may see)', () => {
  it('answers the networks and the viewer’s own organisation name, camel-cased', async () => {
    const response = await call(getList as Handler, await networkRequest(A, 'advisor', '', ''));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      ownOrganisation: OWN_ORGANISATION,
      networks: [{ id: NETWORK_ID, name: 'Sample Network', systemName: 'Sample capacity', pathwayName: 'Sample pathway', timeZone: 'Europe/London' }],
    });
  });

  it('answers an empty list for a tenant that is in no network, never a 404 that says why', async () => {
    const response = await call(getList as Handler, await networkRequest(TENANTS.C, 'advisor', '', ''));
    expect(response.status).toBe(200);
    expect((await response.json()).networks).toEqual([]);
  });

  it.each(ROLES)('the role %s is let in only when it is one that sees a network', async (role) => {
    const response = await call(getList as Handler, await networkRequest(A, role, '', ''));
    expect(response.status).toBe(VIEW_ROLES.includes(role) ? 200 : 403);
  });

  it('refuses the networkId key: this route offers networks, it takes none', async () => {
    const response = await call(getList as Handler, await networkRequest(A, 'advisor', '', 'networkId=net-sample'));
    expect(response.status).toBe(400);
  });
});

describe.each(READS)('GET /api/bff/network/%s', (_name, handler, route, upstream) => {
  it('answers the back end’s answer for the network, asking the registry first', async () => {
    const response = await call(handler, await networkRequest(A, 'advisor', route));
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(seenNetwork.map((c) => `${c.method} ${c.path}`)).toEqual(['GET /networks', `GET ${upstream}`]);
  });

  it('never sends the network id as a query key to the back end, and no other query', async () => {
    await call(handler, await networkRequest(A, 'advisor', route));
    expect(networkCalls().map((c) => c.query)).toEqual(['']);
  });

  it.each(ROLES)('role %s: let in only when it is one that sees a network', async (role) => {
    const response = await call(handler, await networkRequest(A, role, route));
    expect(response.status).toBe(VIEW_ROLES.includes(role) ? 200 : 403);
  });

  it('is the same 404 for a network that is not offered and for a tenant that is not a member, with no call to the network', async () => {
    const unknown = await call(handler, await networkRequest(A, 'advisor', route, { networkId: 'net-other' }));
    const nonMember = await call(handler, await networkRequest(TENANTS.C, 'advisor', route));
    expect(unknown.status).toBe(404);
    expect(nonMember.status).toBe(404);
    expect(await nonMember.text()).toBe(await unknown.text());
    expect(networkCalls()).toEqual([]);
  });

  it('refuses a request with no networkId or a malformed one, with 400, before any call', async () => {
    for (const query of ['', 'networkId=trust-a', 'networkId=net-sample&networkId=net-other']) {
      const response = await call(handler, await networkRequest(A, 'advisor', route, query));
      expect(response.status, query).toBe(400);
    }
    expect(seenNetwork).toEqual([]);
  });

  it('refuses any other key that names a tenant, a scope or a network', async () => {
    for (const query of ['tenant=trust-b', 'scope=network', 'network=net-sample', 'sourceTenantId=trust-b']) {
      const response = await call(handler, await networkRequest(A, 'advisor', route, `networkId=net-sample&${query}`));
      expect(response.status, query).toBe(400);
    }
    expect(seenNetwork).toEqual([]);
  });

  it('answers a member of the other tenant as well: the network is one board for every member', async () => {
    const a = await call(handler, await networkRequest(A, 'advisor', route));
    const b = await call(handler, await networkRequest(TENANTS.B, 'advisor', route));
    expect(await b.json()).toEqual(await a.json());
  });

  it('answers 503 when the back end is down, and 404 when the back end refuses the network', async () => {
    server.use(http.get(`${NETWORK_ROOT}${upstream}`, () => HttpResponse.json({}, { status: 503 })));
    expect((await call(handler, await networkRequest(A, 'advisor', route))).status).toBe(503);
    server.use(http.get(`${NETWORK_ROOT}${upstream}`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found' }] }, { status: 403 })));
    // A refusal that is not a 404 is still the one 404: the answer never says the network exists.
    expect((await call(handler, await networkRequest(A, 'advisor', route))).status).toBe(404);
  });

  it('answers 502 for a body it cannot read, with nothing of the body in the answer', async () => {
    server.use(http.get(`${NETWORK_ROOT}${upstream}`, () => HttpResponse.json({ surprise: 'Secret-Value-9' })));
    const response = await call(handler, await networkRequest(A, 'advisor', route));
    expect(response.status).toBe(502);
    expect(await response.text()).not.toContain('Secret-Value-9');
  });
});

describe('the board answer', () => {
  it('is camel-cased and rebuilt from the fields the page uses, so a field of the back end that is not one never passes', async () => {
    const leaky = { ...BOARD_BODY, tenant_id: 'trust-b', entries: [boardEntry({ source_tenant_id: 'trust-b', grant_id: 'g-1' })] };
    server.use(http.get(`${NETWORK_ROOT}/network/${NETWORK_ID}/board`, () => HttpResponse.json(leaky)));
    const response = await call(getBoard as Handler, await networkRequest(A, 'advisor', '/board'));
    const text = await response.text();
    expect(text).not.toMatch(/trust-b|g-1|tenant|source_/);
    expect(JSON.parse(text).entries[0]).toMatchObject({ rowRef: 'lst-0001', organisationName: OWN_ORGANISATION, serviceName: 'UCR West', status: 'accepting' });
  });
});

describe('the history of the directory and the criteria', () => {
  it('passes history=true on, and nothing else', async () => {
    await call(getDirectory as Handler, await networkRequest(A, 'advisor', '/directory', 'networkId=net-sample&history=true'));
    expect(networkCalls().map((c) => c.query)).toEqual(['history=true']);
  });

  it('refuses a history value that is not true or false, before any call', async () => {
    const response = await call(getDirectory as Handler, await networkRequest(A, 'advisor', '/directory', 'networkId=net-sample&history=maybe'));
    expect(response.status).toBe(400);
    expect(seenNetwork).toEqual([]);
  });
});

describe('GET /api/bff/network/week', () => {
  it('answers the week of a Monday, for an executive and a shift lead only', async () => {
    for (const role of ['exec', 'lead'] as Role[]) {
      const response = await call(getWeek as Handler, await networkRequest(A, role, '/week', 'networkId=net-sample&weekStart=2026-10-19'));
      expect(response.status, role).toBe(200);
      expect((await response.json()).weekStart).toBe('2026-10-19');
    }
    for (const role of ROLES.filter((r) => r !== 'exec' && r !== 'lead')) {
      const response = await call(getWeek as Handler, await networkRequest(A, role, '/week', 'networkId=net-sample&weekStart=2026-10-19'));
      expect(response.status, role).toBe(403);
    }
  });

  it('asks the back end for that Monday', async () => {
    await call(getWeek as Handler, await networkRequest(A, 'exec', '/week', 'networkId=net-sample&weekStart=2026-10-19'));
    expect(networkCalls().map((c) => c.query)).toEqual(['weekStart=2026-10-19']);
  });

  it('refuses a day that is not a Monday, a malformed one and a missing one, before any call', async () => {
    for (const query of ['weekStart=2026-10-20', 'weekStart=yesterday', 'weekStart=2026-02-30', '']) {
      const response = await call(getWeek as Handler, await networkRequest(A, 'exec', '/week', `networkId=net-sample&${query}`));
      expect(response.status, query).toBe(400);
    }
    expect(seenNetwork).toEqual([]);
  });

  it('is the one 404 for a network that is not offered', async () => {
    const response = await call(getWeek as Handler, await networkRequest(TENANTS.C, 'exec', '/week', 'networkId=net-sample&weekStart=2026-10-19'));
    expect(response.status).toBe(404);
    expect(networkCalls()).toEqual([]);
  });
});
