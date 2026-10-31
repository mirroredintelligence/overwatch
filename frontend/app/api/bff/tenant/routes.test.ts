// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ROLES } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import {
  ONE_TIME_CODE,
  RAW_LOG,
  RAW_OVERVIEW,
  RAW_SETTINGS,
  RAW_TICKETS,
  RAW_VERSIONS,
  VIEW_LOG,
  VIEW_OVERVIEW,
  VIEW_TICKETS,
  VIEW_VERSIONS,
} from '@/test/fixtures/tenantAdmin';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { requestAs } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

// The tenant administrator's BFF routes (TEN-076, W9C-routes.md): one per back-end route of `/tenant`,
// each for the role `tenant-admin` and no other, with the person's own token, the idempotency key of a
// write passed on, and an answer that holds only what a screen shows: never a secret reference, the
// tenant's id, an account's opaque reference or a hash. The back end's answers are the real route
// module's shapes (test/fixtures/tenantAdmin.ts).

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const A = TENANTS.A;

type Verb = 'GET' | 'POST' | 'PUT' | 'DELETE';
type Case = {
  name: string;
  /** The route module and the verb it exports. */
  module: () => Promise<Record<string, unknown>>;
  verb: Verb;
  /** The path the browser calls, and the context of a dynamic route. */
  url: string;
  params?: Record<string, string>;
  /** What the browser sends as the body, and what the back end must be sent. */
  body?: unknown;
  backendBody?: unknown;
  backend: { path: string; status?: number; reply?: unknown };
  /** What the browser gets back. */
  status?: number;
  view?: unknown;
};

const CASES: Case[] = [
  { name: 'overview', module: () => import('./overview/route'), verb: 'GET', url: '/api/bff/tenant/overview', backend: { path: '/tenant/overview', reply: RAW_OVERVIEW }, view: VIEW_OVERVIEW },
  {
    name: 'settings',
    module: () => import('./settings/route'),
    verb: 'GET',
    url: '/api/bff/tenant/settings',
    backend: { path: '/tenant/settings', reply: RAW_SETTINGS },
    view: RAW_SETTINGS,
  },
  { name: 'versions', module: () => import('./config/versions/route'), verb: 'GET', url: '/api/bff/tenant/config/versions', backend: { path: '/tenant/config/versions', reply: RAW_VERSIONS }, view: VIEW_VERSIONS },
  {
    name: 'one version',
    module: () => import('./config/versions/[n]/route'),
    verb: 'GET',
    url: '/api/bff/tenant/config/versions/3',
    params: { n: '3' },
    backend: { path: '/tenant/config/versions/3', reply: RAW_VERSIONS.versions[0] },
    view: VIEW_VERSIONS.versions[0],
  },
  {
    name: 'draft',
    module: () => import('./config/drafts/route'),
    verb: 'POST',
    url: '/api/bff/tenant/config/drafts',
    body: { basedOn: 2, changes: { pressureWatchFrom: 5, twiceADaySecondTime: '14:30', alertDefaultKinds: ['not-updated'] }, removals: ['systemName'], reasonCode: 'review' },
    backendBody: { basedOn: 2, changes: { pressureWatchFrom: 5, twiceADaySecondTime: '14:30', alertDefaultKinds: ['not-updated'] }, removals: ['systemName'], reasonCode: 'review' },
    backend: { path: '/tenant/config/drafts', status: 201, reply: { version: 4, changedKeys: ['pressureWatchFrom'], clinicalKeys: ['pressureWatchFrom'], approvalsRequired: 2 } },
    status: 201,
    view: { version: 4, changedKeys: ['pressureWatchFrom'], clinicalKeys: ['pressureWatchFrom'], approvalsRequired: 2 },
  },
  {
    name: 'approval of a version',
    module: () => import('./config/versions/[n]/approval/route'),
    verb: 'POST',
    url: '/api/bff/tenant/config/versions/3/approval',
    params: { n: '3' },
    backendBody: {},
    backend: { path: '/tenant/config/versions/3/approval', reply: { version: 3, status: 'pending-approval', approvals: 1, approvalsRequired: 2 } },
    view: { version: 3, status: 'pending-approval', approvals: 1, approvalsRequired: 2 },
  },
  {
    name: 'contact',
    module: () => import('./contacts/route'),
    verb: 'PUT',
    url: '/api/bff/tenant/contacts',
    body: { kind: 'coordination-phone', label: 'Access team A', value: '01632 960001' },
    backendBody: { kind: 'coordination-phone', label: 'Access team A', value: '01632 960001' },
    backend: { path: '/tenant/contacts', status: 204 },
    status: 204,
  },
  {
    name: 'new email channel',
    module: () => import('./channels/route'),
    verb: 'POST',
    url: '/api/bff/tenant/channels',
    body: { kind: 'email', senderLabel: 'Sample A team', fromAddress: 'noreply@a.example.test', fromDisplayName: 'Sample A' },
    backendBody: { kind: 'email', senderLabel: 'Sample A team', fromAddress: 'noreply@a.example.test', fromDisplayName: 'Sample A' },
    backend: { path: '/tenant/channels', status: 201, reply: { id: 'ch-new', secretRef: 'tenants/trust-a/smtp' } },
    status: 201,
    view: { id: 'ch-new' },
  },
  {
    name: 'change an email channel',
    module: () => import('./channels/[id]/route'),
    verb: 'PUT',
    url: '/api/bff/tenant/channels/ch-email',
    params: { id: 'ch-email' },
    body: { kind: 'email', senderLabel: 'Sample A team', fromAddress: 'noreply@a.example.test', status: 'retired' },
    backendBody: { kind: 'email', senderLabel: 'Sample A team', fromAddress: 'noreply@a.example.test', status: 'retired' },
    backend: { path: '/tenant/channels/ch-email', reply: { id: 'ch-email' } },
    view: { id: 'ch-email' },
  },
  {
    name: 'retention',
    module: () => import('./retention/route'),
    verb: 'PUT',
    url: '/api/bff/tenant/retention',
    body: { rules: [{ dataClass: 'bookings', keepDays: 365, action: 'delete' }, { dataClass: 'audit-chain', keepDays: null, action: 'keep' }] },
    backendBody: { rules: [{ dataClass: 'bookings', keepDays: 365, action: 'delete' }, { dataClass: 'audit-chain', keepDays: null, action: 'keep' }] },
    backend: { path: '/tenant/retention', reply: { stored: 2 } },
    view: { stored: 2 },
  },
  {
    name: 'directory',
    module: () => import('./directory/route'),
    verb: 'PUT',
    url: '/api/bff/tenant/directory',
    body: { directoryId: '11111111-1111-4111-8111-111111111111' },
    backendBody: { directoryId: '11111111-1111-4111-8111-111111111111' },
    backend: { path: '/tenant/directory', status: 204 },
    status: 204,
  },
  {
    name: 'role mapping',
    module: () => import('./role-mappings/route'),
    verb: 'PUT',
    url: '/api/bff/tenant/role-mappings',
    body: { groupObjectId: 'cccccccc-0000-4000-8000-000000000001', role: 'lead', status: 'active' },
    backendBody: { groupObjectId: 'cccccccc-0000-4000-8000-000000000001', role: 'lead', status: 'active' },
    backend: { path: '/tenant/role-mappings', status: 204 },
    status: 204,
  },
  { name: 'access log', module: () => import('./access-log/route'), verb: 'GET', url: '/api/bff/tenant/access-log?days=30', backend: { path: '/tenant/access-log', reply: RAW_LOG }, view: VIEW_LOG },
  { name: 'tickets', module: () => import('./support-tickets/route'), verb: 'GET', url: '/api/bff/tenant/support-tickets', backend: { path: '/tenant/support-tickets', reply: RAW_TICKETS }, view: VIEW_TICKETS },
  {
    name: 'approval of a ticket',
    module: () => import('./support-tickets/[id]/approval/route'),
    verb: 'POST',
    url: '/api/bff/tenant/support-tickets/tkt-1/approval',
    params: { id: 'tkt-1' },
    backendBody: {},
    backend: { path: '/tenant/support-tickets/tkt-1/approval', reply: { ticket: { ...RAW_TICKETS.tickets[0], state: 'approved', decidedByRef: 'stf-x', decidedAt: '2026-10-30T09:00:00Z' }, code: ONE_TIME_CODE, codeExpiresAt: '2026-10-30T13:00:00Z' } },
    view: { ticket: { ...VIEW_TICKETS.tickets[0], state: 'approved', decidedAt: '2026-10-30T09:00:00Z' }, code: ONE_TIME_CODE, codeExpiresAt: '2026-10-30T13:00:00Z' },
  },
  {
    name: 'refusal of a ticket',
    module: () => import('./support-tickets/[id]/refusal/route'),
    verb: 'POST',
    url: '/api/bff/tenant/support-tickets/tkt-1/refusal',
    params: { id: 'tkt-1' },
    backendBody: {},
    backend: { path: '/tenant/support-tickets/tkt-1/refusal', reply: { ...RAW_TICKETS.tickets[0], state: 'refused' } },
    view: { ...VIEW_TICKETS.tickets[0], state: 'refused' },
  },
  {
    name: 'revocation of an access',
    module: () => import('./support-tickets/[id]/access/route'),
    verb: 'DELETE',
    url: '/api/bff/tenant/support-tickets/tkt-3/access',
    params: { id: 'tkt-3' },
    backend: { path: '/tenant/support-tickets/tkt-3/access', reply: { ...RAW_TICKETS.tickets[2], state: 'revoked' } },
    view: { ...VIEW_TICKETS.tickets[2], state: 'revoked' },
  },
];

type Seen = { method: string; path: string; search: string; authorization: string | null; idempotencyKey: string | null; contentType: string | null; headers: Headers; body: unknown };
let seen: Seen[] = [];

function handleBackend(c: Case, override?: { status: number; reply?: unknown }) {
  const url = `${ROOT}${c.backend.path}`;
  const make = { GET: http.get, POST: http.post, PUT: http.put, DELETE: http.delete }[c.verb];
  server.use(
    make(url, async ({ request }) => {
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
      return status === 204 ? new HttpResponse(null, { status }) : HttpResponse.json((reply ?? {}) as Record<string, unknown>, { status });
    }),
  );
}

const UNSAFE = (verb: Verb) => verb !== 'GET';

async function call(c: Case, role: (typeof ROLES)[number] | null, options: { csrf?: boolean; key?: string | null; body?: unknown } = {}) {
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
      ? new Request(`https://${A.host}${c.url}`, { method: c.verb, headers: { Host: A.host, ...headers }, body: hasBody ? JSON.stringify(body ?? {}) : undefined })
      : await requestAs(A, role, { method: c.verb, path: c.url, headers, csrf: options.csrf ?? UNSAFE(c.verb) ? true : undefined, body: hasBody ? JSON.stringify(body ?? {}) : undefined });
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
  it('answers 401 with no session, and calls nothing', async () => {
    handleBackend(c);
    const response = await call(c, null);
    expect(response.status).toBe(401);
    expect(seen).toEqual([]);
  });

  it('is for the tenant administrator and for no other role: every other of the 13 roles is a 403 and calls nothing', async () => {
    handleBackend(c);
    for (const role of ROLES) {
      seen = [];
      const response = await call(c, role);
      if (role === 'tenant-admin') {
        expect(response.status, role).toBe(c.status ?? 200);
        expect(seen, role).toHaveLength(1);
      } else {
        expect(response.status, role).toBe(403);
        expect(seen, role).toEqual([]);
      }
    }
  });

  it('calls the back end’s own route with the person’s token, and no tenant, scope or network', async () => {
    handleBackend(c);
    await call(c, 'tenant-admin');
    expect(seen).toHaveLength(1);
    const [one] = seen as [Seen];
    expect(one.method).toBe(c.verb);
    expect(one.path).toBe(c.backend.path);
    expect(one.authorization).toMatch(/^Bearer [A-Za-z0-9._-]+$/);
    for (const name of one.headers.keys()) expect(name).not.toMatch(/tenant|scope|network/i);
    if (UNSAFE(c.verb) && c.verb !== 'DELETE') {
      expect(one.body).toEqual(c.backendBody ?? c.body);
      expect(one.contentType).toMatch(/json/);
    }
  });

  it('answers what a screen shows, and nothing else', async () => {
    handleBackend(c);
    const response = await call(c, 'tenant-admin');
    expect(response.status).toBe(c.status ?? 200);
    if (c.view === undefined) {
      expect(await response.text()).toBe('');
    } else {
      const text = await response.text();
      expect(JSON.parse(text)).toEqual(c.view);
      expect(text).not.toMatch(/secretRef|tenants\/trust-a|ACsample|stf-|ops-|"trust-a"|createdByRef|approvedByRefs|requestedByRef|decidedByRef|actorRef|accountSid|hash/i);
    }
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it('says the back end is unavailable, never an empty answer, when it is', async () => {
    handleBackend(c, { status: 503, reply: {} });
    const response = await call(c, 'tenant-admin');
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: expect.any(String), message: expect.any(String) });
  });

  it('passes a refusal on with a fixed message, never the back end’s words', async () => {
    handleBackend(c, { status: 409, reply: { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict', diagnostics: 'tenant trust-b holds this' }] } });
    const response = await call(c, 'tenant-admin');
    expect(response.status).toBe(409);
    const text = await response.text();
    expect(text).not.toContain('trust-b');
    expect(JSON.parse(text).code).toBe('conflict');
  });

  if (UNSAFE(c.verb)) {
    it('needs the CSRF token: 403 before any call', async () => {
      handleBackend(c);
      const response = await call(c, 'tenant-admin', { csrf: false });
      expect(response.status).toBe(403);
      expect(seen).toEqual([]);
    });

    it('needs an Idempotency-Key, 400 before any call, and passes the one it has on', async () => {
      handleBackend(c);
      expect((await call(c, 'tenant-admin', { key: null })).status).toBe(400);
      expect((await call(c, 'tenant-admin', { key: 'has a space' })).status).toBe(400);
      expect(seen).toEqual([]);
      await call(c, 'tenant-admin', { key: 'key-for-this-submit' });
      expect(seen[0]?.idempotencyKey).toBe('key-for-this-submit');
    });
  }

  if (c.params !== undefined) {
    it('answers an id that is not the shape of one as the one 404, before any call', async () => {
      handleBackend(c);
      const bad = { ...c, params: Object.fromEntries(Object.keys(c.params!).map((k) => [k, '../etc/passwd'])) };
      const response = await call(bad, 'tenant-admin');
      expect(response.status).toBe(404);
      expect(seen).toEqual([]);
    });
  }
});

describe('the bodies the BFF will not pass on', () => {
  const draft = CASES.find((c) => c.name === 'draft')!;
  const channel = CASES.find((c) => c.name === 'new email channel')!;
  const retention = CASES.find((c) => c.name === 'retention')!;

  it('refuses, with 400 and before any call, a draft that is not the shape of one or names anything else', async () => {
    handleBackend(draft);
    for (const body of [
      { basedOn: 'two', changes: {} },
      { basedOn: -1, changes: {} },
      { basedOn: 1.5, changes: {} },
      { basedOn: 2, changes: [] },
      { basedOn: 2, changes: { a: { nested: true } } },
      { basedOn: 2, removals: 'x' },
      { basedOn: 2, extra: 1 },
      { basedOn: 2, reasonCode: 7 },
      {},
    ]) {
      expect((await call(draft, 'tenant-admin', { body })).status, JSON.stringify(body)).toBe(400);
    }
    expect(seen).toEqual([]);
  });

  it('refuses a text channel and a secret reference: the text channel is the platform operator’s, a secret never goes through a browser', async () => {
    handleBackend(channel);
    for (const body of [
      { kind: 'sms', senderLabel: 'X' },
      { kind: 'email', senderLabel: 'X', secretRef: 'tenants/trust-b/smtp' },
      { kind: 'email' },
      { kind: 'email', senderLabel: 'X', status: 'deleted' },
    ]) {
      expect((await call(channel, 'tenant-admin', { body })).status, JSON.stringify(body)).toBe(400);
    }
    expect(seen).toEqual([]);
  });

  it('refuses a retention body that is neither the defaults nor a list of rules of a known class and action', async () => {
    handleBackend(retention);
    for (const body of [{}, { rules: [{ dataClass: 'x', keepDays: 1, action: 'keep' }] }, { rules: [{ dataClass: 'bookings', keepDays: 0, action: 'keep' }] }, { rules: [{ dataClass: 'bookings', keepDays: 5, action: 'burn' }] }, { useDefaults: true, rules: [] , extra: 1 }]) {
      expect((await call(retention, 'tenant-admin', { body })).status, JSON.stringify(body)).toBe(400);
    }
    expect(seen).toEqual([]);
    const defaults = await call(retention, 'tenant-admin', { body: { useDefaults: true } });
    expect(defaults.status).toBe(200);
    expect(seen[0]?.body).toEqual({ useDefaults: true });
  });
});

describe('the answers that need the person: whose draft it is, and the code shown once', () => {
  it('says whether a version is the signed-in person’s own draft or already approved by them, and never who else', async () => {
    const versions = CASES.find((c) => c.name === 'versions')!;
    const raw = { versions: [{ ...RAW_VERSIONS.versions[0]!, createdByRef: 'stf-0000000000000000000000000002', approvedByRefs: ['stf-trust-a0000000000000000000000000'] }] };
    handleBackend({ ...versions, backend: { ...versions.backend, reply: raw } });
    const body = await (await call(versions, 'tenant-admin')).json();
    expect(body.versions[0]).toMatchObject({ authoredByYou: false, approvedByYou: true, approvals: 1 });
  });

  it('gives the one-time code in the approval’s answer and nowhere else, and never stores it', async () => {
    const approval = CASES.find((c) => c.name === 'approval of a ticket')!;
    handleBackend(approval);
    const response = await call(approval, 'tenant-admin');
    const body = await response.json();
    expect(body.code).toBe(ONE_TIME_CODE);
    expect(response.headers.get('cache-control')).toMatch(/no-store/);
    expect(response.headers.get('set-cookie')).toBeNull();
    // The listing does not carry it, whatever the back end sends.
    const list = CASES.find((c) => c.name === 'tickets')!;
    handleBackend({ ...list, backend: { ...list.backend, reply: { tickets: [{ ...RAW_TICKETS.tickets[1]!, code: ONE_TIME_CODE, codeHash: 'abc' }] } } });
    expect(await (await call(list, 'tenant-admin')).text()).not.toMatch(new RegExp(`${ONE_TIME_CODE}|codeHash`));
  });

  it('answers a back end that sends a shape it does not know as a failure, never a half page', async () => {
    const overview = CASES.find((c) => c.name === 'overview')!;
    handleBackend({ ...overview, backend: { ...overview.backend, reply: { tenant: 'x' } } });
    expect((await call(overview, 'tenant-admin')).status).toBeGreaterThanOrEqual(500);
  });
});

describe('the access log window', () => {
  it('asks for the days the page named, between 1 and 400, and for 90 when it names none or nonsense', async () => {
    const log = CASES.find((c) => c.name === 'access log')!;
    handleBackend(log);
    for (const [url, days] of [
      ['/api/bff/tenant/access-log?days=30', '30'],
      ['/api/bff/tenant/access-log', '90'],
      ['/api/bff/tenant/access-log?days=0', '90'],
      ['/api/bff/tenant/access-log?days=9999', '90'],
      ['/api/bff/tenant/access-log?days=abc', '90'],
    ] as const) {
      seen = [];
      await call({ ...log, url }, 'tenant-admin');
      expect(seen[0]?.search, url).toBe(`?days=${days}`);
    }
  });
});
