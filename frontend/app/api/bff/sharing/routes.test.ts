// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROLES, type Role } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { MEMBER_NETWORKS, OWNER_NETWORKS, SHARING } from '@/test/fixtures/network-admin-shapes';
import { ADMIN_ROOT, adminBackendHandlers, MEMBER, NETWORK_ID, OWNER, resetAdminBackend, seenAdmin } from '@/test/msw/handlers/networkAdminBackend';
import { server } from '@/test/msw/server';
import { requestAs } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

// The member administrator's sharing BFF routes (TEN-081): what the organisation shares with each network,
// the proposal, approval, refusal and end of a grant, leaving the network and accepting an agreement version.
// Each is for the role `tenant-admin` and no other. The organisation is the session's; the network is the
// registry's answer for it (the browser may name one it was offered as `networkId`, the one key the input
// guard lets through on the routes that need a network) and an agreement is accepted by the network, never by
// a handle the browser holds. Every answer holds only what a screen shows.

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${ADMIN_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetAdminBackend();
  server.use(...adminBackendHandlers);
});
afterEach(() => vi.unstubAllEnvs());

type Handler = (request: Request, context?: unknown) => Promise<Response>;
type Module = Record<string, Handler>;

const ROUTES = {
  overview: () => import('./route') as Promise<Module>,
  propose: () => import('./grants/route') as Promise<Module>,
  approve: () => import('./grants/[id]/approve/route') as Promise<Module>,
  decline: () => import('./grants/[id]/decline/route') as Promise<Module>,
  end: () => import('./grants/[id]/end/route') as Promise<Module>,
  leave: () => import('./leave/route') as Promise<Module>,
  agreement: () => import('./agreement/route') as Promise<Module>,
} as const;
type Name = keyof typeof ROUTES;

const BASE = '/api/bff/sharing';
const PATHS: Record<Name, [verb: 'GET' | 'POST', url: string, params?: Record<string, string>]> = {
  overview: ['GET', BASE],
  propose: ['POST', `${BASE}/grants`],
  approve: ['POST', `${BASE}/grants/grant-3/approve`, { id: 'grant-3' }],
  decline: ['POST', `${BASE}/grants/grant-3/decline`, { id: 'grant-3' }],
  end: ['POST', `${BASE}/grants/grant-2/end`, { id: 'grant-2' }],
  leave: ['POST', `${BASE}/leave`],
  agreement: ['POST', `${BASE}/agreement`],
};
const BODIES: Partial<Record<Name, unknown>> = {
  propose: { scope: 'capacity' },
  agreement: { agreementVersion: 2 },
};
/** The routes that need a network of the organisation's. A grant is found by its own handle. */
const NEEDS_NETWORK: Name[] = ['propose', 'leave', 'agreement'];

/** The member's networks as the back end lists them when the person must accept a newer agreement. */
const BEHIND = {
  networks: [{ ...MEMBER_NETWORKS.networks[0]!, agreement_version: 2, agreement_behind: true }],
};

async function call(
  name: Name,
  options: { role?: Role; tenant?: (typeof TENANTS)[keyof typeof TENANTS]; query?: string; body?: unknown; csrf?: boolean; params?: Record<string, string>; url?: string } = {},
): Promise<Response> {
  const [verb, url, params] = PATHS[name];
  const module = await ROUTES[name]();
  const handler = module[verb] as Handler;
  const body = options.body === undefined ? BODIES[name] : options.body;
  const request = await requestAs(options.tenant ?? MEMBER, options.role ?? 'tenant-admin', {
    method: verb,
    path: `${options.url ?? url}${options.query ? `?${options.query}` : ''}`,
    csrf: verb === 'POST' && options.csrf !== false ? true : undefined,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return handler(request, { params: Promise.resolve(options.params ?? params ?? {}) });
}

const backend = () => seenAdmin.map((c) => `${c.method} ${c.path}`);
const writes = () => seenAdmin.filter((c) => c.method === 'POST');
const NAMES = Object.keys(ROUTES) as Name[];

describe('who may call', () => {
  it.each(NAMES)('%s: only the tenant administrator, never another role, and nothing is asked of the back end', async (name) => {
    // The agreement route needs a network that is waiting for an acceptance to get past the choice.
    if (name === 'agreement') server.use(http.get(`${ADMIN_ROOT}/network-admin/networks`, () => HttpResponse.json(BEHIND)));
    for (const role of ROLES) {
      resetAdminBackend();
      const response = await call(name, { role });
      if (role === 'tenant-admin') {
        expect(response.status, `${name} ${role}`).not.toBe(403);
      } else {
        expect(response.status, `${name} ${role}`).toBe(403);
        expect(backend(), `${name} ${role}`).toEqual([]);
      }
    }
  });

  it.each(NAMES.filter((n) => PATHS[n][0] === 'POST'))('%s: a write without the CSRF token is refused before any work', async (name) => {
    const response = await call(name, { csrf: false });
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ code: 'csrf' });
    expect(backend()).toEqual([]);
  });

  it.each(NAMES)('%s: every answer is private and not stored', async (name) => {
    expect((await call(name)).headers.get('cache-control')).toContain('no-store');
  });

  it('the network administrator is not a member’s administrator: it gets none of these', async () => {
    for (const name of NAMES) expect((await call(name, { role: 'network-admin', tenant: OWNER })).status, name).toBe(403);
    expect(backend()).toEqual([]);
  });
});

describe('what the organisation shares', () => {
  it('answers the organisation’s own code, the allowlist, and for each network its membership, what the network holds and its own grants', async () => {
    const response = await call('overview');
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(Object.keys(body).sort()).toEqual(['allowlist', 'networks', 'organisationCode']);
    expect(body.organisationCode).toBe(MEMBER.id);
    expect(body.allowlist).toEqual({ version: 1, scopes: SHARING.allowlist.scopes });
    expect(body.networks).toHaveLength(1);
    const [network] = body.networks;
    expect(network).toMatchObject({
      id: NETWORK_ID,
      name: 'Sample Network',
      membershipStatus: 'active',
      joinedAt: '2026-10-02T09:00:00Z',
      leftAt: null,
      agreementReference: 'DSA-2026-1',
      agreementVersion: 1,
      acceptedAgreementVersion: 1,
      agreementBehind: false,
    });
    expect(network.shared).toEqual([
      { kind: 'capacity', status: 'active', endedAt: null, endReason: null },
      { kind: 'directory', status: 'ended', endedAt: '2026-10-29T10:00:00Z', endReason: 'grant-ended' },
    ]);
    expect(network.grants.map((g: { id: string }) => g.id)).toEqual(['grant-3', 'grant-4']);
    expect(Object.keys(network.grants[0]).sort()).toEqual(
      ['agreementVersion', 'allowlistVersion', 'effective', 'effectiveFrom', 'effectiveTo', 'endReason', 'endedAt', 'grantorApprovedAt', 'id', 'organisation', 'ownerApprovedAt', 'scope', 'status', 'version'].sort(),
    );
  });

  it('asks the back end for the organisation’s own sharing and own grants, with its own token, naming nothing', async () => {
    await call('overview');
    expect(backend().sort()).toEqual(['GET /network-admin/grants', 'GET /network-admin/sharing']);
    expect(seenAdmin.every((c) => c.query === '' && c.tenant === MEMBER.id && c.role === 'tenant-admin')).toBe(true);
  });

  it('keeps each network’s grants with that network and never another organisation’s', async () => {
    const own = { ...SHARING.networks[0]! };
    const second = { ...own, id: 'net-second', name: 'Second Network', membership_id: 'mem-z' };
    server.use(http.get(`${ADMIN_ROOT}/network-admin/sharing`, () => HttpResponse.json({ allowlist: SHARING.allowlist, networks: [own, second] })));
    const body = await (await call('overview')).json();
    expect(body.networks.map((n: { id: string }) => n.id)).toEqual([NETWORK_ID, 'net-second']);
    // The fixture's grants belong to net-sample: the second network has none.
    expect(body.networks[1].grants).toEqual([]);
    expect(body.networks[0].grants).toHaveLength(2);
  });

  it('holds no tenant id but the organisation’s own, no membership handle and none of the back end’s own names', async () => {
    const text = await (await call('overview')).text();
    expect(text).not.toMatch(new RegExp(`${OWNER.id}|trust-a`));
    expect(text).not.toMatch(/mem-a|membership|network_id|network_name|organisation_name|is_owner|tenant_id/i);
  });

  it('answers an organisation in no network with the allowlist and no network, and still its own code', async () => {
    const body = await (await call('overview', { tenant: TENANTS.C })).json();
    expect(body.networks).toEqual([]);
    expect(body.organisationCode).toBe(TENANTS.C.id);
    expect(body.allowlist.version).toBe(1);
  });

  it('says only what the back end said about the allowlist: a field it adds is in the answer, so the screen can say it cannot list it', async () => {
    const wider = { ...SHARING.allowlist, scopes: { ...SHARING.allowlist.scopes, capacity: [...SHARING.allowlist.scopes.capacity, 'new_field'] } };
    server.use(http.get(`${ADMIN_ROOT}/network-admin/sharing`, () => HttpResponse.json({ ...SHARING, allowlist: wider })));
    const body = await (await call('overview')).json();
    expect(body.allowlist.scopes.capacity).toContain('new_field');
  });

  it('is a 502 with nothing of the body when the back end answers what is not expected, and a 503 when it is down', async () => {
    server.use(http.get(`${ADMIN_ROOT}/network-admin/sharing`, () => HttpResponse.json({ allowlist: { version: 1, scopes: {} }, networks: [], surprise: 'Secret-Value-9' })));
    const bad = await call('overview');
    expect(bad.status).toBe(502);
    expect(await bad.text()).not.toContain('Secret-Value-9');
    server.use(http.get(`${ADMIN_ROOT}/network-admin/grants`, () => HttpResponse.json({}, { status: 503 })));
    server.use(http.get(`${ADMIN_ROOT}/network-admin/sharing`, () => HttpResponse.json(SHARING)));
    expect((await call('overview')).status).toBe(503);
  });

  it('takes no network id: the organisation’s sharing is every network’s', async () => {
    const response = await call('overview', { query: `networkId=${NETWORK_ID}` });
    expect(response.status).toBe(400);
    expect(backend()).toEqual([]);
  });
});

describe('which network: the registry decides, never the browser', () => {
  it.each(NEEDS_NETWORK)('%s: asks the registry first and names the network only in the path or the body of the call after', async (name) => {
    if (name === 'agreement') server.use(http.get(`${ADMIN_ROOT}/network-admin/networks`, () => HttpResponse.json(BEHIND)));
    const response = await call(name);
    expect(response.status).not.toBe(404);
    expect(response.status).toBeLessThan(500);
  });

  it.each(NEEDS_NETWORK)('%s: an organisation that is in no network gets the one 404, and nothing is written', async (name) => {
    const response = await call(name, { tenant: TENANTS.C });
    expect(response.status).toBe(404);
    expect(writes()).toEqual([]);
  });

  it.each(NEEDS_NETWORK)('%s: a network id that was never offered is the same 404 as one that is not the organisation’s', async (name) => {
    const unknown = await call(name, { query: 'networkId=net-other' });
    const stranger = await call(name, { tenant: TENANTS.C });
    expect(unknown.status).toBe(404);
    expect(await unknown.text()).toBe(await stranger.text());
    expect(writes()).toEqual([]);
  });

  it.each(NAMES)('%s: any other key that names a tenant, a scope or a network is a 400 before any call', async (name) => {
    for (const query of ['tenant=trust-b', 'scope=network', 'network=net-sample', 'networkIds=net-sample']) {
      expect((await call(name, { query })).status, `${name} ${query}`).toBe(400);
    }
    expect(backend()).toEqual([]);
  });

  it.each(NEEDS_NETWORK)('%s: a second networkId, or one that is not a network id, is a 400 before any call', async (name) => {
    for (const query of [`networkId=${NETWORK_ID}&networkId=net-other`, 'networkId=trust-a', 'networkId=NET-SAMPLE']) {
      expect((await call(name, { query })).status, `${name} ${query}`).toBe(400);
    }
    expect(backend()).toEqual([]);
  });

  it('with more than one network and none named, a route that needs one is a 400; naming an offered one works', async () => {
    const own = MEMBER_NETWORKS.networks[0]!;
    server.use(http.get(`${ADMIN_ROOT}/network-admin/networks`, () => HttpResponse.json({ networks: [own, { ...own, id: 'net-second', name: 'Second' }] })));
    expect((await call('propose')).status).toBe(400);
    expect(writes()).toEqual([]);
    const named = await call('propose', { query: 'networkId=net-second' });
    expect(named.status).toBe(404); // the stand-in back end only has net-sample: the choice reached the path
    expect(writes()[0]?.body).toMatchObject({ network_id: 'net-second' });
  });
});

describe('proposing sharing', () => {
  it.each(['capacity', 'directory', 'criteria'])('proposes %s for the network the organisation is in, and answers the grant’s handle', async (scope) => {
    const response = await call('propose', { body: { scope } });
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ id: 'grant-new', status: 'proposed' });
    expect(writes()[0]).toMatchObject({ path: '/network-admin/grants', body: { network_id: NETWORK_ID, scope }, role: 'tenant-admin', tenant: MEMBER.id });
  });

  it.each([
    ['no scope', {}],
    ['a scope that is not one', { scope: 'everything' }],
    ['a scope that is not text', { scope: 7 }],
    ['a window the screen does not offer', { scope: 'capacity', effectiveFrom: '2026-11-01T00:00:00Z' }],
    ['another field', { scope: 'capacity', purpose: 'x' }],
  ])('refuses %s with 400 before any call', async (_name, body) => {
    expect((await call('propose', { body })).status).toBe(400);
    expect(backend()).toEqual([]);
  });

  it('refuses a body that names a network or a tenant (the input guard), before any work', async () => {
    for (const body of [{ scope: 'capacity', network_id: NETWORK_ID }, { scope: 'capacity', networkId: NETWORK_ID }, { scope: 'capacity', tenant_id: OWNER.id }]) {
      expect((await call('propose', { body })).status).toBe(400);
    }
    expect(backend()).toEqual([]);
  });

  it('answers a scope that already has an open grant with the standard conflict words', async () => {
    server.use(http.post(`${ADMIN_ROOT}/network-admin/grants`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict' }] }, { status: 409 })));
    const response = await call('propose');
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ code: 'conflict', message: 'That changed while you were working. Reload and try again.' });
  });
});

describe('approving, declining and ending a grant', () => {
  it.each([
    ['approve', 'approve', { effective: false }],
    ['decline', 'decline', { status: 'declined' }],
    ['end', 'end', { status: 'ended' }],
  ] as const)('%s: by the grant’s handle, with the person’s own token, and a small answer', async (name, action, answer) => {
    const response = await call(name);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(answer);
    expect(backend()).toEqual([`POST /network-admin/grants/${PATHS[name][2]!.id}/${action}`]);
    expect(seenAdmin[0]).toMatchObject({ role: 'tenant-admin', tenant: MEMBER.id });
  });

  it.each(NAMES.filter((n) => ['approve', 'decline', 'end'].includes(n)))('%s: takes no network id at all, and no body', async (name) => {
    expect((await call(name, { query: `networkId=${NETWORK_ID}` })).status).toBe(400);
    expect((await call(name, { body: { reason: 'x' } })).status).toBe(400);
    expect(backend()).toEqual([]);
  });

  it.each(['approve', 'decline', 'end'] as const)('%s: a grant that is not the organisation’s, or a handle that is not a handle, is the one 404', async (name) => {
    const unknown = await call(name, { params: { id: 'zzz' }, url: `${BASE}/grants/zzz/${name}` });
    expect(unknown.status).toBe(404);
    resetAdminBackend();
    for (const id of ['', 'a b', '../x', 'x'.repeat(80), '%2e']) {
      expect((await call(name, { params: { id }, url: `${BASE}/grants/x/${name}` })).status, id).toBe(404);
    }
    expect(backend()).toEqual([]);
  });

  it('answers a conflict, such as the same person giving both approvals, in the standard words', async () => {
    server.use(http.post(`${ADMIN_ROOT}/network-admin/grants/:g/approve`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict' }] }, { status: 409 })));
    const response = await call('approve');
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ code: 'conflict', message: 'That changed while you were working. Reload and try again.' });
  });

  it('is the one 404 when the back end refuses with a 403', async () => {
    server.use(http.post(`${ADMIN_ROOT}/network-admin/grants/:g/end`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'forbidden' }] }, { status: 403 })));
    expect((await call('end')).status).toBe(404);
  });
});

describe('leaving the network', () => {
  it('leaves the network the organisation is in, and says how much ended', async () => {
    const response = await call('leave');
    expect(await response.json()).toEqual({ status: 'left', grantsLapsed: 1, listingsWithdrawn: 0 });
    expect(backend()).toContain(`POST /network-admin/network/${NETWORK_ID}/leave`);
  });

  it('is not offered to the network’s owner: it cannot leave its own network', async () => {
    server.use(http.get(`${ADMIN_ROOT}/network-admin/networks`, () => HttpResponse.json(OWNER_NETWORKS)));
    const response = await call('leave', { tenant: OWNER });
    expect(response.status).toBe(404);
    expect(writes()).toEqual([]);
  });

  it('takes no body', async () => {
    expect((await call('leave', { body: { reason: 'x' } })).status).toBe(400);
    expect(backend()).toEqual([]);
  });
});

describe('accepting an agreement version', () => {
  const behind = () => server.use(http.get(`${ADMIN_ROOT}/network-admin/networks`, () => HttpResponse.json(BEHIND)));

  it('accepts the version the administrator read, for the network that waits for it, by the membership the server holds', async () => {
    behind();
    const response = await call('agreement');
    expect(await response.json()).toEqual({ status: 'active' });
    expect(writes()[0]).toMatchObject({ path: '/network-admin/memberships/mem-a/accept', body: { agreement_version: 2 }, role: 'tenant-admin', tenant: MEMBER.id });
  });

  it('is the one 404 when no network of the organisation waits for an acceptance: nothing to accept is nothing to ask', async () => {
    const response = await call('agreement');
    expect(response.status).toBe(404);
    expect(writes()).toEqual([]);
  });

  it('accepts a first invitation too', async () => {
    server.use(http.get(`${ADMIN_ROOT}/network-admin/networks`, () => HttpResponse.json({ networks: [{ ...MEMBER_NETWORKS.networks[0]!, membership_status: 'invited' }] })));
    expect((await call('agreement')).status).toBe(200);
  });

  it.each([
    ['no version', {}],
    ['a version that is not a whole number', { agreementVersion: 1.5 }],
    ['version 0', { agreementVersion: 0 }],
    ['a version that is text', { agreementVersion: '2' }],
    ['a membership handle', { agreementVersion: 2, membershipId: 'mem-a' }],
    ['another field', { agreementVersion: 2, reference: 'x' }],
  ])('refuses %s with 400 before any call', async (_name, body) => {
    behind();
    expect((await call('agreement', { body })).status).toBe(400);
    expect(backend()).toEqual([]);
  });

  it('answers a version that is not the current one with the standard conflict words', async () => {
    behind();
    server.use(http.post(`${ADMIN_ROOT}/network-admin/memberships/:m/accept`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict' }] }, { status: 409 })));
    expect((await call('agreement')).status).toBe(409);
  });
});
