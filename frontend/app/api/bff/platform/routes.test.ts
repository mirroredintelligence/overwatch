// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROLES } from '@/lib/auth/session';
import { OPERATOR_ROLES, type OperatorRole } from '@/lib/operator/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import {
  RAW_AUDIT,
  RAW_DETAIL_PROVISIONING,
  RAW_SUPPORT_TICKETS,
  RAW_TENANTS_OPERATOR,
  RAW_TENANTS_SUPPORT,
  VIEW_AUDIT,
  VIEW_DETAIL_PROVISIONING,
  VIEW_SUPPORT_TICKETS,
  VIEW_TENANTS_OPERATOR,
  VIEW_TENANTS_SUPPORT,
  rawTicket,
  viewTicket,
} from '@/test/fixtures/operator';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { requestAsOperator } from '@/test/operator';
import { server } from '@/test/msw/server';
import { requestAs } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

// The operator console's BFF routes (TEN-083, W9C-routes.md): one per back-end route of `/platform`, each for
// the roles the back end gives it (the platform operator, or a support person) and no other, called with the
// OPERATOR's own token. The tenant a route acts on is the one in its path (the back end checks the token and
// the role before it looks at it); no body, query or header of ours names one. The answers hold only what a
// screen shows: never the reference of a secret, and never an answer that is not the shape expected.

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const OPERATOR: OperatorRole[] = ['platform-operator'];
const SUPPORT: OperatorRole[] = ['support'];

type Verb = 'GET' | 'POST' | 'PUT' | 'DELETE';
type Case = {
  name: string;
  module: () => Promise<Record<string, unknown>>;
  verb: Verb;
  url: string;
  params?: Record<string, string>;
  roles: OperatorRole[];
  body?: unknown;
  backendBody?: unknown;
  backend: { path: string; status?: number; reply?: unknown };
  status?: number;
  view?: unknown;
};

const NEW_TENANT = { displayName: 'Sample Area D', legalName: 'Sample Area D Organisation', organisationType: 'gp-practice', countryCode: 'GB', timeZone: 'Europe/London', odsCode: 'RZZ03' };
const T = '/api/bff/platform/tenants/trust-b';
const P = { id: 'trust-b' };

const CASES: Case[] = [
  { name: 'tenants (operator)', module: () => import('./tenants/route'), verb: 'GET', url: '/api/bff/platform/tenants', roles: OPERATOR, backend: { path: '/platform/tenants', reply: RAW_TENANTS_OPERATOR }, view: VIEW_TENANTS_OPERATOR },
  { name: 'tenant detail', module: () => import('./tenants/[id]/route'), verb: 'GET', url: T, params: P, roles: OPERATOR, backend: { path: '/platform/tenants/trust-b', reply: RAW_DETAIL_PROVISIONING }, view: VIEW_DETAIL_PROVISIONING },
  {
    name: 'create a tenant',
    module: () => import('./tenants/[id]/route'),
    verb: 'PUT',
    url: '/api/bff/platform/tenants/trust-d',
    params: { id: 'trust-d' },
    roles: OPERATOR,
    body: NEW_TENANT,
    backendBody: NEW_TENANT,
    backend: { path: '/platform/tenants/trust-d', status: 201, reply: { tenantId: 'trust-d', created: true, recorded: true } },
    status: 201,
    view: { created: true, recorded: true },
  },
  { name: 'host', module: () => import('./tenants/[id]/host/route'), verb: 'PUT', url: `${T}/host`, params: P, roles: OPERATOR, body: { host: 'tenant-b.example.test' }, backendBody: { host: 'tenant-b.example.test' }, backend: { path: '/platform/tenants/trust-b/host', reply: { recorded: true } }, view: { recorded: true } },
  {
    name: 'record a number',
    module: () => import('./tenants/[id]/numbers/route'),
    verb: 'POST',
    url: `${T}/numbers`,
    params: P,
    roles: OPERATOR,
    body: { e164: '+441632960002', accountSid: 'ACsampleaccount00000000000000000001', senderLabel: 'SampleB' },
    backendBody: { e164: '+441632960002', accountSid: 'ACsampleaccount00000000000000000001', senderLabel: 'SampleB' },
    backend: { path: '/platform/tenants/trust-b/numbers', status: 201, reply: { channelId: 'ch-1', recorded: true } },
    status: 201,
    view: { recorded: true },
  },
  { name: 'mark a number tested', module: () => import('./tenants/[id]/numbers/tested/route'), verb: 'POST', url: `${T}/numbers/tested`, params: P, roles: OPERATOR, body: { e164: '+441632960002' }, backendBody: { e164: '+441632960002' }, backend: { path: '/platform/tenants/trust-b/numbers/tested', reply: { recorded: true } }, view: { recorded: true } },
  {
    name: 'references',
    module: () => import('./tenants/[id]/references/route'),
    verb: 'PUT',
    url: `${T}/references`,
    params: P,
    roles: OPERATOR,
    body: { dsaRef: 'DSA-2026-014', dpiaRef: 'DPIA-77' },
    backendBody: { dsaRef: 'DSA-2026-014', dpiaRef: 'DPIA-77' },
    backend: { path: '/platform/tenants/trust-b/references', reply: { references: ['dsa_ref', 'dpia_ref'], recorded: true } },
    view: { references: ['dsa_ref', 'dpia_ref'], recorded: true },
  },
  { name: 'verify a directory', module: () => import('./tenants/[id]/directory/verification/route'), verb: 'POST', url: `${T}/directory/verification`, params: P, roles: OPERATOR, body: { directoryId: '11111111-1111-4111-8111-111111111111' }, backendBody: { directoryId: '11111111-1111-4111-8111-111111111111' }, backend: { path: '/platform/tenants/trust-b/directory/verification', reply: { recorded: true } }, view: { recorded: true } },
  {
    name: 'invite the first administrator',
    module: () => import('./tenants/[id]/admin-invitation/route'),
    verb: 'POST',
    url: `${T}/admin-invitation`,
    params: P,
    roles: OPERATOR,
    body: { mobile: '07700 900123' },
    backendBody: { mobile: '07700 900123' },
    backend: { path: '/platform/tenants/trust-b/admin-invitation', status: 201, reply: { expiresAt: '2026-11-01T09:00:00Z', recorded: true } },
    status: 201,
    view: { expiresAt: '2026-11-01T09:00:00Z', recorded: true },
  },
  { name: 'activate', module: () => import('./tenants/[id]/activation/route'), verb: 'POST', url: `${T}/activation`, params: P, roles: OPERATOR, backendBody: {}, backend: { path: '/platform/tenants/trust-b/activation', reply: { tenantId: 'trust-b', epoch: 2, seeded: [true, true], recorded: true } }, view: { recorded: true } },
  {
    name: 'suspend',
    module: () => import('./tenants/[id]/suspension/route'),
    verb: 'POST',
    url: `${T}/suspension`,
    params: P,
    roles: OPERATOR,
    body: { mode: 'read-only', reason: 'contract' },
    backendBody: { mode: 'read-only', reason: 'contract' },
    backend: { path: '/platform/tenants/trust-b/suspension', reply: { tenantId: 'trust-b', epoch: 3, mode: 'read-only', recorded: true } },
    view: { mode: 'read-only', recorded: true },
  },
  { name: 'resume', module: () => import('./tenants/[id]/suspension/route'), verb: 'DELETE', url: `${T}/suspension`, params: P, roles: OPERATOR, backend: { path: '/platform/tenants/trust-b/suspension', reply: { tenantId: 'trust-b', epoch: 4, servicesPrompted: 3, servicesAnnounced: 1, resumedAgain: false, recorded: true } }, view: { servicesPrompted: 3, servicesAnnounced: 1, resumedAgain: false, recorded: true } },
  {
    name: 'start offboarding',
    module: () => import('./tenants/[id]/offboarding/route'),
    verb: 'POST',
    url: `${T}/offboarding`,
    params: P,
    roles: OPERATOR,
    body: { confirm: 'trust-b' },
    backendBody: { confirmTenantId: 'trust-b' },
    backend: { path: '/platform/tenants/trust-b/offboarding', reply: { tenantId: 'trust-b', startedAt: '2026-10-30T09:00:00Z', noticeEndsAt: '2026-11-29T09:00:00Z', recorded: true } },
    view: { startedAt: '2026-10-30T09:00:00Z', noticeEndsAt: '2026-11-29T09:00:00Z', recorded: true },
  },
  { name: 'audit', module: () => import('./audit/route'), verb: 'GET', url: '/api/bff/platform/audit?afterSeq=0&limit=50', roles: OPERATOR, backend: { path: '/platform/audit', reply: RAW_AUDIT }, view: VIEW_AUDIT },
  { name: 'verify the chain', module: () => import('./audit/verification/route'), verb: 'GET', url: '/api/bff/platform/audit/verification', roles: OPERATOR, backend: { path: '/platform/audit/verification', reply: { intact: true } }, view: { intact: true } },
  { name: 'support tickets', module: () => import('./support-tickets/route'), verb: 'GET', url: '/api/bff/platform/support-tickets', roles: SUPPORT, backend: { path: '/platform/support-tickets', reply: RAW_SUPPORT_TICKETS }, view: VIEW_SUPPORT_TICKETS },
  {
    name: 'ask for access',
    module: () => import('./tenants/[id]/support-tickets/route'),
    verb: 'POST',
    url: '/api/bff/platform/tenants/trust-a/support-tickets',
    params: { id: 'trust-a' },
    roles: SUPPORT,
    body: { reasonCode: 'service-fault', reason: 'The board shows a service twice', reference: 'HD-1042' },
    backendBody: { reasonCode: 'service-fault', reason: 'The board shows a service twice', reference: 'HD-1042' },
    backend: { path: '/platform/tenants/trust-a/support-tickets', status: 201, reply: rawTicket() },
    status: 201,
    view: viewTicket(rawTicket()),
  },
  { name: 'one ticket', module: () => import('./support-tickets/[ticket]/route'), verb: 'GET', url: '/api/bff/platform/support-tickets/tkt-1', params: { ticket: 'tkt-1' }, roles: SUPPORT, backend: { path: '/platform/support-tickets/tkt-1', reply: rawTicket() }, view: viewTicket(rawTicket()) },
  { name: 'cancel a ticket', module: () => import('./support-tickets/[ticket]/cancellation/route'), verb: 'POST', url: '/api/bff/platform/support-tickets/tkt-1/cancellation', params: { ticket: 'tkt-1' }, roles: SUPPORT, backendBody: {}, backend: { path: '/platform/support-tickets/tkt-1/cancellation', reply: rawTicket({ state: 'cancelled' }) }, view: viewTicket(rawTicket({ state: 'cancelled' })) },
  {
    name: 'open an access',
    module: () => import('./support-tickets/[ticket]/access/route'),
    verb: 'POST',
    url: '/api/bff/platform/support-tickets/tkt-2/access',
    params: { ticket: 'tkt-2' },
    roles: SUPPORT,
    body: { code: 'K7R4-92QX' },
    backendBody: { code: 'K7R4-92QX' },
    backend: { path: '/platform/support-tickets/tkt-2/access', reply: { ticket: rawTicket({ id: 'tkt-2', state: 'opened', accessId: 'acc-2' }), access: { accessId: 'acc-2', tenantId: 'trust-a', expiresAt: '2026-10-30T10:00:00Z' } } },
    view: { ticket: viewTicket(rawTicket({ id: 'tkt-2', state: 'opened', accessId: 'acc-2' })), access: { expiresAt: '2026-10-30T10:00:00Z' } },
  },
  { name: 'end an access', module: () => import('./support-tickets/[ticket]/access/route'), verb: 'DELETE', url: '/api/bff/platform/support-tickets/tkt-3/access', params: { ticket: 'tkt-3' }, roles: SUPPORT, backend: { path: '/platform/support-tickets/tkt-3/access', reply: rawTicket({ id: 'tkt-3', state: 'ended' }) }, view: viewTicket(rawTicket({ id: 'tkt-3', state: 'ended' })) },
];

type Seen = { method: string; path: string; search: string; authorization: string | null; idempotencyKey: string | null; contentType: string | null; headers: Headers; body: unknown };
let seen: Seen[] = [];

function handleBackend(c: Case, override?: { status: number; reply?: unknown }) {
  const make = { GET: http.get, POST: http.post, PUT: http.put, DELETE: http.delete }[c.verb];
  server.use(
    make(`${ROOT}${c.backend.path}`, async ({ request }) => {
      const text = await request.clone().text();
      seen.push({
        method: request.method,
        path: new URL(request.url).pathname,
        search: new URL(request.url).search,
        authorization: request.headers.get('authorization'),
        idempotencyKey: request.headers.get('idempotency-key'),
        contentType: request.headers.get('content-type'),
        headers: request.headers,
        body: text === '' ? undefined : JSON.parse(text),
      });
      const status = override?.status ?? c.backend.status ?? 200;
      const reply = override ? override.reply : c.backend.reply;
      return HttpResponse.json((reply ?? {}) as Record<string, unknown>, { status });
    }),
  );
}

const UNSAFE = (verb: Verb) => verb !== 'GET';

async function call(c: Case, role: OperatorRole | null, options: { csrf?: boolean; key?: string | null; body?: unknown } = {}) {
  const mod = await c.module();
  const handler = mod[c.verb] as (request: Request, context?: unknown) => Promise<Response>;
  const headers: Record<string, string> = {};
  const key = options.key === undefined ? 'key-0001' : options.key;
  if (key !== null && UNSAFE(c.verb)) headers['Idempotency-Key'] = key;
  const body = options.body === undefined ? c.body : options.body;
  const hasBody = body !== undefined || (UNSAFE(c.verb) && c.verb !== 'DELETE');
  if (hasBody) headers['Content-Type'] = 'application/json';
  const context = c.params === undefined ? undefined : { params: Promise.resolve(c.params) };
  const request =
    role === null
      ? new Request(`https://console.example.test${c.url}`, { method: c.verb, headers: { Host: 'console.example.test', ...headers }, body: hasBody ? JSON.stringify(body ?? {}) : undefined })
      : await requestAsOperator(role, { method: c.verb, path: c.url, headers, csrf: (options.csrf ?? UNSAFE(c.verb)) ? true : undefined, body: hasBody ? JSON.stringify(body ?? {}) : undefined });
  return handler(request, context);
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  seen = [];
});
afterEach(() => vi.unstubAllEnvs());

describe.each(CASES)('$verb $url ($name)', (c) => {
  const allowed = c.roles[0]!;

  it('answers 401 with no session, and calls nothing', async () => {
    handleBackend(c);
    expect((await call(c, null)).status).toBe(401);
    expect(seen).toEqual([]);
  });

  it('is for the roles the back end gives it: the other operator role is a 403 and calls nothing', async () => {
    handleBackend(c);
    for (const role of OPERATOR_ROLES) {
      seen = [];
      const response = await call(c, role);
      if (c.roles.includes(role)) {
        expect(response.status, role).toBe(c.status ?? 200);
        expect(seen, role).toHaveLength(1);
      } else {
        expect(response.status, role).toBe(403);
        expect(seen, role).toEqual([]);
      }
    }
  });

  it('is a 401 for a tenant’s person of every one of the 13 roles, exactly as for no session, and calls nothing', async () => {
    handleBackend(c);
    const none = await (await call(c, null)).text();
    for (const role of ROLES) {
      const mod = await c.module();
      const handler = mod[c.verb] as (request: Request, context?: unknown) => Promise<Response>;
      const request = await requestAs(TENANTS.A, role, { method: c.verb, host: 'console.example.test', path: c.url, csrf: UNSAFE(c.verb) ? true : undefined, headers: { 'Idempotency-Key': 'k' } });
      const response = await handler(request, c.params === undefined ? undefined : { params: Promise.resolve(c.params) });
      expect(response.status, role).toBe(401);
      expect(await response.text(), role).toBe(none);
    }
    expect(seen).toEqual([]);
  });

  it('calls the back end’s own route with the OPERATOR’s token, and no tenant, scope or network of ours', async () => {
    handleBackend(c);
    await call(c, allowed);
    expect(seen).toHaveLength(1);
    const [one] = seen as [Seen];
    expect(one.method).toBe(c.verb);
    expect(one.path).toBe(c.backend.path);
    expect(one.authorization).toMatch(/^Bearer [A-Za-z0-9._-]+$/);
    const claims = JSON.parse(Buffer.from((one.authorization ?? '').split('.')[1] ?? '', 'base64url').toString()) as Record<string, unknown>;
    expect(claims.aud).toBe('diucs-ops');
    expect(claims).not.toHaveProperty('tenant');
    for (const name of one.headers.keys()) expect(name).not.toMatch(/tenant|scope|network/i);
    if (UNSAFE(c.verb) && c.verb !== 'DELETE') {
      expect(one.body).toEqual(c.backendBody ?? c.body);
      expect(one.contentType).toMatch(/json/);
    }
  });

  it('answers what a screen shows, and nothing else', async () => {
    handleBackend(c);
    const response = await call(c, allowed);
    expect(response.status).toBe(c.status ?? 200);
    const text = await response.text();
    expect(JSON.parse(text)).toEqual(c.view);
    expect(text).not.toMatch(/authTokenRef|secretRef|tenants\/trust-b\/twilio|accessId|"epoch"|hash/i);
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it('says the back end is unavailable, never an empty answer, when it is', async () => {
    handleBackend(c, { status: 503, reply: {} });
    const response = await call(c, allowed);
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: expect.any(String), message: expect.any(String) });
  });

  it('passes a refusal on with a fixed message, never the back end’s words', async () => {
    handleBackend(c, { status: 409, reply: { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict', diagnostics: 'tenant trust-z holds this host' }] } });
    const response = await call(c, allowed);
    expect(response.status).toBe(409);
    const text = await response.text();
    expect(text).not.toContain('trust-z');
    expect(JSON.parse(text).code).toBe('conflict');
  });

  it('says a refusal of the token is a session that has ended, and takes the session away', async () => {
    handleBackend(c, { status: 401, reply: {} });
    const response = await call(c, allowed);
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ code: 'session-ended' });
  });

  if (UNSAFE(c.verb)) {
    it('needs the CSRF token: 403 before any call', async () => {
      handleBackend(c);
      expect((await call(c, allowed, { csrf: false })).status).toBe(403);
      expect(seen).toEqual([]);
    });

    it('needs an Idempotency-Key, 400 before any call, and passes the one it has on', async () => {
      handleBackend(c);
      expect((await call(c, allowed, { key: null })).status).toBe(400);
      expect((await call(c, allowed, { key: 'has a space' })).status).toBe(400);
      expect(seen).toEqual([]);
      await call(c, allowed, { key: 'key-for-this-submit' });
      expect(seen[0]?.idempotencyKey).toBe('key-for-this-submit');
    });
  }

  if (c.params !== undefined) {
    it('answers an id that is not the shape of one as the one 404, before any call', async () => {
      handleBackend(c);
      const bad = { ...c, params: Object.fromEntries(Object.keys(c.params!).map((k) => [k, '../etc/passwd'])) };
      const response = await call(bad, allowed);
      expect(response.status).toBe(404);
      expect(seen).toEqual([]);
    });
  }
});

describe('the list for each role', () => {
  const list = CASES[0]!;
  it('gives a support person the id, the name and the status of a tenant and nothing more, and the operator the rest', async () => {
    handleBackend({ ...list, backend: { ...list.backend, reply: RAW_TENANTS_SUPPORT } });
    const support = await (await call(list, 'support')).json();
    expect(support).toEqual(VIEW_TENANTS_SUPPORT);
    handleBackend(list);
    expect(await (await call(list, 'platform-operator')).json()).toEqual(VIEW_TENANTS_OPERATOR);
  });

  it('does not pass on what a support person must not see even if the back end sent it', async () => {
    handleBackend({ ...list, backend: { ...list.backend, reply: RAW_TENANTS_OPERATOR } });
    const body = await (await call(list, 'support')).json();
    expect(body).toEqual(VIEW_TENANTS_SUPPORT);
    expect(JSON.stringify(body)).not.toMatch(/tenant-a\.example|nhs-trust/);
  });
});

describe('the bodies the BFF will not pass on', () => {
  const byName = (name: string) => CASES.find((c) => c.name === name)!;

  it('refuses a tenant that is created with a body that names anything else, or with a type that is not one', async () => {
    const c = byName('create a tenant');
    handleBackend(c);
    for (const body of [{ ...NEW_TENANT, extra: 1 }, { ...NEW_TENANT, organisationType: 'company' }, { ...NEW_TENANT, displayName: '' }, { displayName: 'x' }, {}, [] as unknown]) {
      expect((await call(c, 'platform-operator', { body })).status, JSON.stringify(body)).toBe(400);
    }
    expect(seen).toEqual([]);
  });

  it('refuses an offboarding whose confirmation is not the tenant’s own id, before any call', async () => {
    const c = byName('start offboarding');
    handleBackend(c);
    for (const body of [{ confirm: 'trust-a' }, { confirm: '' }, {}, { confirm: 'trust-b', extra: 1 }, { confirmTenantId: 'trust-b' }]) {
      expect((await call(c, 'platform-operator', { body })).status, JSON.stringify(body)).toBe(400);
    }
    expect(seen).toEqual([]);
  });

  it('refuses a suspension that is not a known mode and reason', async () => {
    const c = byName('suspend');
    handleBackend(c);
    for (const body of [{ mode: 'off', reason: 'contract' }, { mode: 'blocked', reason: 'because' }, { mode: 'blocked' }, { reason: 'contract' }]) {
      expect((await call(c, 'platform-operator', { body })).status).toBe(400);
    }
    expect(seen).toEqual([]);
  });

  it('refuses references that are empty, a number that is not E.164 and a mobile that is not a UK mobile', async () => {
    handleBackend(byName('references'));
    expect((await call(byName('references'), 'platform-operator', { body: {} })).status).toBe(400);
    handleBackend(byName('record a number'));
    expect((await call(byName('record a number'), 'platform-operator', { body: { e164: '01632 960002', accountSid: 'AC1', senderLabel: 'S' } })).status).toBe(400);
    handleBackend(byName('invite the first administrator'));
    expect((await call(byName('invite the first administrator'), 'platform-operator', { body: { mobile: '0161 496 0000' } })).status).toBe(400);
    expect((await call(byName('invite the first administrator'), 'platform-operator', { body: { mobile: '07700 900123', tenant: 'x' } })).status).toBe(400);
    expect(seen).toEqual([]);
  });

  it('refuses a ticket request with a reason that is not a plain sentence, an unknown reason code or an extra field', async () => {
    const c = byName('ask for access');
    handleBackend(c);
    for (const body of [
      { reasonCode: 'service-fault', reason: 'short' },
      { reasonCode: 'made-up', reason: 'The board shows a service twice' },
      { reasonCode: 'service-fault', reason: 'The board shows a service twice', tenantId: 'trust-b' },
      { reasonCode: 'service-fault', reason: 'Call <b>me</b> about the board please' },
      { reasonCode: 'service-fault', reason: 'x'.repeat(201) },
    ]) {
      expect((await call(c, 'support', { body })).status, JSON.stringify(body)).toBe(400);
    }
    expect(seen).toEqual([]);
  });

  it('refuses a code that is not the shape of one, before any call', async () => {
    const c = byName('open an access');
    handleBackend(c);
    for (const body of [{ code: 'abc' }, { code: '' }, {}, { code: 'K7R4-92QX', extra: 1 }, { code: 'K7R492QX' }]) {
      expect((await call(c, 'support', { body })).status, JSON.stringify(body)).toBe(400);
    }
    expect(seen).toEqual([]);
  });
});

describe('what the answers never carry', () => {
  it('drops the reference of a number’s auth token and any account reference but the sid the operator needs', async () => {
    const c = CASES.find((x) => x.name === 'tenant detail')!;
    handleBackend(c);
    const text = await (await call(c, 'platform-operator')).text();
    expect(text).not.toMatch(/authTokenRef|tenants\/trust-b\/twilio/);
    expect(JSON.parse(text).numbers[0]).toEqual({ e164: '+441632960002', accountSid: 'ACsampleaccount00000000000000000001', status: 'active', testedAt: null, quarantineUntil: null, hasSecret: true });
  });

  it('is a failure, never a half page, when the detail is not the shape expected', async () => {
    const c = CASES.find((x) => x.name === 'tenant detail')!;
    handleBackend({ ...c, backend: { ...c.backend, reply: { tenant: { id: 'trust-b' } } } });
    expect((await call(c, 'platform-operator')).status).toBeGreaterThanOrEqual(500);
  });

  it('asks the chain for the page the console named, between 1 and 200 entries, and refuses nothing it can correct', async () => {
    const c = CASES.find((x) => x.name === 'audit')!;
    handleBackend(c);
    for (const [url, expected] of [
      ['/api/bff/platform/audit?afterSeq=10&limit=25', '?afterSeq=10&limit=25'],
      ['/api/bff/platform/audit', '?afterSeq=0&limit=50'],
      ['/api/bff/platform/audit?afterSeq=-1&limit=0', '?afterSeq=0&limit=50'],
      ['/api/bff/platform/audit?afterSeq=abc&limit=9999', '?afterSeq=0&limit=50'],
    ] as const) {
      seen = [];
      await call({ ...c, url }, 'platform-operator');
      expect(seen[0]?.search, url).toBe(expected);
    }
  });
});
