// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROLES, type Role } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { OWNER_NETWORKS } from '@/test/fixtures/network-admin-shapes';
import {
  ADMIN_ROOT,
  adminBackendHandlers,
  MEMBER,
  NETWORK_ID,
  OWNER,
  resetAdminBackend,
  seenAdmin,
} from '@/test/msw/handlers/networkAdminBackend';
import { server } from '@/test/msw/server';
import { requestAs } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

// The network administrator's BFF routes (TEN-080): one per back-end route of `/network-admin` the screens
// use, each for the role `network-admin` and no other. The network is the registry's answer: the browser
// may name one of the networks the server offered (`networkId`, the one key the input guard lets through,
// on the routes that need a network) and never anything else; the back end is asked again on every call.
// Every answer holds only what a screen shows. The back end's answers are the real converters' shapes
// (test/fixtures/network-admin-shapes.ts).

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
  invite: () => import('./members/route') as Promise<Module>,
  remove: () => import('./members/[id]/remove/route') as Promise<Module>,
  agreement: () => import('./agreement/route') as Promise<Module>,
  grants: () => import('./grants/route') as Promise<Module>,
  approve: () => import('./grants/[id]/approve/route') as Promise<Module>,
  declineGrant: () => import('./grants/[id]/decline/route') as Promise<Module>,
  listings: () => import('./listings/route') as Promise<Module>,
  admit: () => import('./listings/[id]/admit/route') as Promise<Module>,
  reinstate: () => import('./listings/[id]/reinstate/route') as Promise<Module>,
  declineListing: () => import('./listings/[id]/decline/route') as Promise<Module>,
  suspend: () => import('./listings/[id]/suspend/route') as Promise<Module>,
} as const;
type Name = keyof typeof ROUTES;

const BASE = '/api/bff/network-admin';
const PATHS: Record<Name, [verb: 'GET' | 'POST', url: string, params?: Record<string, string>]> = {
  overview: ['GET', BASE],
  invite: ['POST', `${BASE}/members`],
  remove: ['POST', `${BASE}/members/mem-a/remove`, { id: 'mem-a' }],
  agreement: ['POST', `${BASE}/agreement`],
  grants: ['GET', `${BASE}/grants`],
  approve: ['POST', `${BASE}/grants/grant-1/approve`, { id: 'grant-1' }],
  declineGrant: ['POST', `${BASE}/grants/grant-3/decline`, { id: 'grant-3' }],
  listings: ['GET', `${BASE}/listings`],
  admit: ['POST', `${BASE}/listings/lst-1/admit`, { id: 'lst-1' }],
  reinstate: ['POST', `${BASE}/listings/lst-3/reinstate`, { id: 'lst-3' }],
  declineListing: ['POST', `${BASE}/listings/lst-1/decline`, { id: 'lst-1' }],
  suspend: ['POST', `${BASE}/listings/lst-2/suspend`, { id: 'lst-2' }],
};
const BODIES: Partial<Record<Name, unknown>> = {
  invite: { organisationCode: 'sample-area-c' },
  agreement: { reference: 'DSA-2026-2', version: 2 },
  declineListing: { reason: 'outside-area' },
  suspend: { reason: 'data-quality' },
};
/** Routes that name no network: a grant is found by its own handle and the back end checks the owner. */
const NO_NETWORK: Name[] = ['approve', 'declineGrant'];

async function call(
  name: Name,
  options: { role?: Role; tenant?: (typeof TENANTS)[keyof typeof TENANTS]; query?: string; body?: unknown; csrf?: boolean; params?: Record<string, string>; url?: string } = {},
): Promise<Response> {
  const [verb, url, params] = PATHS[name];
  const module = await ROUTES[name]();
  const handler = module[verb] as Handler;
  const body = options.body === undefined ? BODIES[name] : options.body;
  const request = await requestAs(options.tenant ?? OWNER, options.role ?? 'network-admin', {
    method: verb,
    path: `${options.url ?? url}${options.query ? `?${options.query}` : ''}`,
    csrf: verb === 'POST' && options.csrf !== false ? true : undefined,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return handler(request, { params: Promise.resolve(options.params ?? params ?? {}) });
}

const backend = () => seenAdmin.map((c) => `${c.method} ${c.path}`);
const NAMES = Object.keys(ROUTES) as Name[];

describe('who may call', () => {
  it.each(NAMES)('%s: only the network administrator, never another role, and nothing is asked of the back end', async (name) => {
    for (const role of ROLES) {
      resetAdminBackend();
      const response = await call(name, { role });
      if (role === 'network-admin') {
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
    const response = await call(name);
    expect(response.headers.get('cache-control')).toContain('no-store');
  });
});

describe('which network: the registry decides, never the browser', () => {
  it('uses the one network the organisation owns, asking the registry first and naming it only in the path', async () => {
    const response = await call('overview');
    expect(response.status).toBe(200);
    expect(backend()).toEqual([
      'GET /network-admin/networks',
      `GET /network-admin/network/${NETWORK_ID}/members`,
      `GET /network-admin/network/${NETWORK_ID}/projection`,
    ]);
    expect(seenAdmin.every((c) => c.query === '')).toBe(true);
    expect(seenAdmin.every((c) => c.tenant === OWNER.id && c.role === 'network-admin')).toBe(true);
  });

  it.each(NAMES.filter((n) => !NO_NETWORK.includes(n)))('%s: another organisation’s administrator, a member’s and a stranger’s get the one 404, and no network route is called', async (name) => {
    const stranger = await call(name, { tenant: TENANTS.C });
    const member = await call(name, { tenant: MEMBER });
    for (const response of [stranger, member]) {
      expect(response.status, name).toBe(404);
      expect(await response.clone().json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
    }
    expect((await stranger.text())).toBe(await member.text());
    expect(backend().filter((line) => line.includes('/network/'))).toEqual([]);
  });

  it.each(NAMES.filter((n) => !NO_NETWORK.includes(n)))('%s: a network id that was never offered is the same 404 as one that is not the caller’s', async (name) => {
    const unknown = await call(name, { query: 'networkId=net-other' });
    const stranger = await call(name, { tenant: TENANTS.C });
    expect(unknown.status).toBe(404);
    expect(await unknown.text()).toBe(await stranger.text());
    expect(backend().filter((line) => line.includes('/network/'))).toEqual([]);
  });

  it.each(NAMES.filter((n) => !NO_NETWORK.includes(n)))('%s: the offered network may be named, once, and still the registry is asked', async (name) => {
    const response = await call(name, { query: `networkId=${NETWORK_ID}` });
    expect(response.status).not.toBe(404);
    expect(backend()[0]).toBe('GET /network-admin/networks');
  });

  it.each(NAMES)('%s: any other key that names a tenant, a scope or a network is a 400 before any call', async (name) => {
    for (const query of ['tenant=trust-b', 'scope=network', 'network=net-sample', 'networkIds=net-sample', 'sourceTenantId=x']) {
      const response = await call(name, { query });
      expect(response.status, `${name} ${query}`).toBe(400);
    }
    expect(backend()).toEqual([]);
  });

  it.each(NAMES)('%s: a second networkId, or one that is not a network id, is a 400 before any call', async (name) => {
    for (const query of [`networkId=${NETWORK_ID}&networkId=net-other`, 'networkId=trust-a', 'networkId=net-', 'networkId=NET-SAMPLE']) {
      const response = await call(name, { query });
      expect(response.status, `${name} ${query}`).toBe(400);
    }
    expect(backend()).toEqual([]);
  });

  it.each(NO_NETWORK)('%s: takes no network id at all', async (name) => {
    const response = await call(name, { query: `networkId=${NETWORK_ID}` });
    expect(response.status).toBe(400);
    expect(backend()).toEqual([]);
  });

  it('when the organisation owns more than one network the overview offers them and chooses none', async () => {
    const second = { ...OWNER_NETWORKS.networks[0]!, id: 'net-second', name: 'Second Network' };
    server.use(http.get(`${ADMIN_ROOT}/network-admin/networks`, () => HttpResponse.json({ networks: [OWNER_NETWORKS.networks[0], second] })));
    const response = await call('overview');
    const body = await response.json();
    expect(response.status).toBe(200);
    expect(body.network).toBeNull();
    expect(body.networks).toEqual([
      { id: 'net-sample', name: 'Sample Network' },
      { id: 'net-second', name: 'Second Network' },
    ]);
    expect(backend()).toEqual(['GET /network-admin/networks']);
  });

  it('with more than one network and none named, a route that needs one is a 400; naming an owned one works; naming a member-only one is a 404', async () => {
    const second = { ...OWNER_NETWORKS.networks[0]!, id: 'net-second', name: 'Second' };
    const memberOnly = { ...OWNER_NETWORKS.networks[0]!, id: 'net-third', name: 'Third', is_owner: false };
    server.use(http.get(`${ADMIN_ROOT}/network-admin/networks`, () => HttpResponse.json({ networks: [OWNER_NETWORKS.networks[0], second, memberOnly] })));
    expect((await call('grants')).status).toBe(400);
    expect((await call('grants', { query: 'networkId=net-second' })).status).not.toBe(400);
    expect((await call('grants', { query: 'networkId=net-third' })).status).toBe(404);
    expect(backend().some((line) => line.includes('/network/net-third'))).toBe(false);
  });
});

describe('the overview', () => {
  it('answers the network, its members, and what each member’s sharing is, field by field', async () => {
    const body = await (await call('overview')).json();
    expect(body.networks).toEqual([{ id: NETWORK_ID, name: 'Sample Network' }]);
    expect(body.network).toMatchObject({ id: NETWORK_ID, name: 'Sample Network', agreementReference: 'DSA-2026-1', agreementVersion: 1 });
    expect(body.network.members).toHaveLength(6);
    expect(body.network.members[1]).toEqual({
      id: 'mem-a',
      organisation: 'Sample Area A',
      role: 'member',
      status: 'active',
      invitedAt: '2026-10-01T09:00:00Z',
      joinedAt: '2026-10-02T09:00:00Z',
      leftAt: null,
      acceptedAgreementVersion: 1,
      agreementBehind: false,
    });
    expect(body.network.members.find((m: { id: string }) => m.id === 'mem-b')).toMatchObject({ agreementBehind: true });
    expect(body.network.health).toEqual([
      {
        id: 'mem-a',
        organisation: 'Sample Area A',
        kinds: [
          { kind: 'capacity', status: 'active', endedAt: null, endReason: null },
          { kind: 'directory', status: 'active', endedAt: null, endReason: null },
        ],
      },
      {
        id: 'mem-d',
        organisation: 'Sample Area D',
        kinds: [{ kind: 'capacity', status: 'ended', endedAt: '2026-10-28T10:00:00Z', endReason: 'left' }],
      },
    ]);
  });

  it('holds no tenant id, no account reference and none of the back end’s own names', async () => {
    const text = await (await call('overview')).text();
    expect(text).not.toMatch(/trust-a|trust-b|tenant|account|is_owner|membership_id|organisation_name/i);
  });

  it('a field the back end adds never passes', async () => {
    server.use(
      http.get(`${ADMIN_ROOT}/network-admin/network/:id/members`, () =>
        HttpResponse.json({ members: [{ membership_id: 'mem-x', organisation_name: 'Sample X', role: 'member', status: 'active', invited_at: '2026-10-01T09:00:00Z', joined_at: null, left_at: null, accepted_agreement_version: null, agreement_behind: false, tenant_id: 'trust-z', account_ref: 'acct-1' }] }),
      ),
    );
    const text = await (await call('overview')).text();
    expect(text).toContain('Sample X');
    expect(text).not.toMatch(/trust-z|acct-1|tenant_id|account_ref/);
  });

  it('is a 502 with nothing of the body when the back end answers what is not expected, and a 503 when it is down', async () => {
    server.use(http.get(`${ADMIN_ROOT}/network-admin/network/:id/members`, () => HttpResponse.json({ members: [{ surprise: 'Secret-Value-9' }] })));
    const bad = await call('overview');
    expect(bad.status).toBe(502);
    expect(await bad.text()).not.toContain('Secret-Value-9');
    server.use(http.get(`${ADMIN_ROOT}/network-admin/networks`, () => HttpResponse.json({}, { status: 503 })));
    expect((await call('overview')).status).toBe(503);
  });

  it('a network the organisation does not own has no overview even if it is a member', async () => {
    server.use(http.get(`${ADMIN_ROOT}/network-admin/networks`, () => HttpResponse.json({ networks: [{ ...OWNER_NETWORKS.networks[0], is_owner: false }] })));
    const response = await call('overview');
    expect(response.status).toBe(404);
    expect(backend()).toEqual(['GET /network-admin/networks']);
  });
});

describe('members and the agreement', () => {
  it('invites by organisation code: the code goes to the back end as the one field it takes, and the answer is the new membership’s handle', async () => {
    const response = await call('invite');
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ id: 'mem-new', status: 'invited' });
    const sent = seenAdmin.find((c) => c.method === 'POST');
    expect(sent?.path).toBe(`/network-admin/network/${NETWORK_ID}/members`);
    expect(sent?.body).toEqual({ tenant_id: 'sample-area-c' });
    expect(sent?.contentType).toContain('json');
  });

  it('answers an unknown organisation, one already in the network and one already invited with the same words, so no list of organisations can be built', async () => {
    const unknown = await call('invite', { body: { organisationCode: 'nobody-here' } });
    const already = await call('invite', { body: { organisationCode: 'sample-area-b' } });
    expect(unknown.status).toBe(404);
    expect(already.status).toBe(404);
    expect(await already.text()).toBe(await unknown.text());
  });

  it.each([
    ['no code', {}],
    ['an empty code', { organisationCode: '' }],
    ['a code with capitals', { organisationCode: 'Sample-Area-C' }],
    ['a code with a space', { organisationCode: 'sample area' }],
    ['a code that is too long', { organisationCode: 'a'.repeat(40) }],
    ['a code that is not text', { organisationCode: 7 }],
    ['another field', { organisationCode: 'sample-area-c', role: 'owner' }],
  ])('refuses %s with 400 before any call', async (_name, body) => {
    const response = await call('invite', { body });
    expect(response.status).toBe(400);
    expect(backend()).toEqual([]);
  });

  it('refuses a body that names a tenant, with 400 before any work (the input guard)', async () => {
    const response = await call('invite', { body: { tenant_id: 'sample-area-c' } });
    expect(response.status).toBe(400);
    expect(backend()).toEqual([]);
  });

  it('ends a membership by its handle and says how much it ended', async () => {
    const response = await call('remove');
    expect(await response.json()).toEqual({ status: 'removed', grantsLapsed: 2, listingsWithdrawn: 1 });
    expect(backend()).toContain(`POST /network-admin/network/${NETWORK_ID}/members/mem-a/remove`);
  });

  it('a membership that is not the network’s is the one 404, and a handle that is not a handle never reaches the back end', async () => {
    const unknown = await call('remove', { params: { id: 'mem-zzz' }, url: `${BASE}/members/mem-zzz/remove` });
    expect(unknown.status).toBe(404);
    resetAdminBackend();
    for (const id of ['', 'a b', '../x', 'x'.repeat(80), '%2e%2e']) {
      const response = await call('remove', { params: { id }, url: `${BASE}/members/x/remove` });
      expect(response.status, id).toBe(404);
    }
    expect(backend().filter((line) => line.includes('/members/'))).toEqual([]);
  });

  it('records an agreement version: the reference and the version, nothing else', async () => {
    const response = await call('agreement');
    expect(await response.json()).toEqual({ agreementVersion: 2 });
    expect(seenAdmin.find((c) => c.method === 'POST')?.body).toEqual({ reference: 'DSA-2026-2', version: 2 });
  });

  it.each([
    ['no reference', { version: 2 }],
    ['a reference with a space', { reference: 'DSA 2026', version: 2 }],
    ['a reference that is too long', { reference: 'D'.repeat(65), version: 2 }],
    ['a reference that looks like an address', { reference: 'a@b.example', version: 2 }],
    ['a version that is not a whole number', { reference: 'DSA-2', version: 1.5 }],
    ['version 0', { reference: 'DSA-2', version: 0 }],
    ['a version that is text', { reference: 'DSA-2', version: '2' }],
    ['the agreement’s content', { reference: 'DSA-2', version: 2, content: 'text of the agreement' }],
  ])('refuses %s with 400 before any call', async (_name, body) => {
    const response = await call('agreement', { body });
    expect(response.status).toBe(400);
    expect(backend()).toEqual([]);
  });
});

describe('grants', () => {
  it('answers the network’s grants by the organisation’s name, with what the screen needs and no more', async () => {
    const body = await (await call('grants')).json();
    expect(body.network).toEqual({ id: NETWORK_ID, name: 'Sample Network' });
    expect(body.grants).toHaveLength(7);
    expect(body.grants[0]).toEqual({
      id: 'grant-1',
      organisation: 'Sample Area A',
      scope: 'capacity',
      status: 'grantor-approved',
      version: 1,
      effectiveFrom: '2026-10-04T09:00:00Z',
      effectiveTo: null,
      agreementVersion: 1,
      allowlistVersion: 1,
      grantorApprovedAt: '2026-10-04T09:00:00Z',
      ownerApprovedAt: null,
      endedAt: null,
      endReason: null,
      effective: false,
    });
    expect(JSON.stringify(body)).not.toMatch(/supersedes|network_id|network_name|organisation_name/);
  });

  it('approves and declines by the grant’s handle; the first approval is not yet effective and the second is', async () => {
    const first = await call('approve');
    expect(await first.json()).toEqual({ effective: true });
    expect(backend()).toEqual(['POST /network-admin/grants/grant-1/approve']);
    expect(seenAdmin[0]?.role).toBe('network-admin');
    const declined = await call('declineGrant');
    expect(await declined.json()).toEqual({ status: 'declined' });
  });

  it('a grant that is not found, or not the owner’s to decide, is the one 404', async () => {
    const response = await call('approve', { params: { id: 'zzz' }, url: `${BASE}/grants/zzz/approve` });
    expect(response.status).toBe(404);
    server.use(http.post(`${ADMIN_ROOT}/network-admin/grants/:g/approve`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'forbidden' }] }, { status: 403 })));
    expect((await call('approve')).status).toBe(404);
  });

  it('answers a conflict (the same person cannot give both approvals) in the standard words', async () => {
    server.use(http.post(`${ADMIN_ROOT}/network-admin/grants/:g/approve`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict' }] }, { status: 409 })));
    const response = await call('approve');
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ code: 'conflict', message: 'That changed while you were working. Reload and try again.' });
  });

  it('refuses a handle that is not a handle before any call', async () => {
    for (const id of ['a b', '../x', 'x'.repeat(80), '%2e']) {
      const response = await call('approve', { params: { id }, url: `${BASE}/grants/x/approve` });
      expect(response.status, id).toBe(404);
    }
    expect(backend()).toEqual([]);
  });
});

describe('listings', () => {
  it('answers the network’s listings by the organisation’s name and the service’s reference', async () => {
    const body = await (await call('listings')).json();
    expect(body.network).toEqual({ id: NETWORK_ID, name: 'Sample Network' });
    expect(body.listings[0]).toEqual({
      id: 'lst-1',
      organisation: 'Sample Area A',
      serviceRef: 'svc-ucr-west',
      status: 'pending',
      reason: null,
      requestedAt: '2026-10-06T09:00:00Z',
      decidedAt: null,
    });
    expect(body.listings.find((l: { id: string }) => l.id === 'lst-3')).toMatchObject({ status: 'suspended', reason: 'data-quality' });
  });

  it.each([
    ['admit', 'admit', undefined],
    ['reinstate', 'reinstate', undefined],
  ] as const)('%s sends no body of its own', async (name, action) => {
    const response = await call(name);
    expect(await response.json()).toEqual({ status: 'done' });
    const sent = seenAdmin.find((c) => c.method === 'POST');
    expect(sent?.path).toMatch(new RegExp(`/listings/lst-\\d/${action}$`));
    expect(sent?.body ?? {}).toEqual({});
  });

  it.each([
    ['declineListing', 'decline', 'outside-area'],
    ['suspend', 'suspend', 'data-quality'],
  ] as const)('%s sends the reason code', async (name, action, reason) => {
    const response = await call(name);
    expect(await response.json()).toEqual({ status: 'done' });
    const sent = seenAdmin.find((c) => c.method === 'POST');
    expect(sent?.path).toMatch(new RegExp(`/listings/lst-\\d/${action}$`));
    expect(sent?.body).toEqual({ reason });
  });

  it.each(['outside-area', 'outside-pilot', 'duplicate-listing', 'data-quality', 'safety-concern', 'agreement-breach', 'other'])('accepts the reason code %s', async (reason) => {
    expect((await call('declineListing', { body: { reason } })).status).toBe(200);
  });

  it.each([
    ['no reason', {}],
    ['a reason in words', { reason: 'They have too many' }],
    ['a reason code that is not one', { reason: 'outside' }],
    ['a reason that is not text', { reason: 4 }],
    ['another field', { reason: 'other', note: 'free text' }],
  ])('refuses %s with 400 before any call', async (_name, body) => {
    for (const name of ['declineListing', 'suspend'] as const) {
      const response = await call(name, { body });
      expect(response.status, `${name}`).toBe(400);
    }
    expect(backend()).toEqual([]);
  });

  it('admit and reinstate refuse a body: a reason is for a decline or a pause only', async () => {
    for (const name of ['admit', 'reinstate'] as const) {
      const response = await call(name, { body: { reason: 'other' } });
      expect(response.status, name).toBe(400);
    }
    expect(backend()).toEqual([]);
  });

  it('a listing that is not the network’s is the one 404', async () => {
    const response = await call('admit', { params: { id: 'zzz' }, url: `${BASE}/listings/zzz/admit` });
    expect(response.status).toBe(404);
  });
});
