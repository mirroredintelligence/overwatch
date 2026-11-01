import type { IncomingMessage, ServerResponse } from 'node:http';

// The platform (operator console) routes of the stand-in back end, for the browser tests (TEN-083). Only an
// operator token that starts with OPERATOR_LIVE_PREFIX is served, each with its own private set of tenants, so
// parallel tests never touch each other's; any other token (and the plain `e2e-operator-token` the older tests
// use) gets the 404 it always had, which the console says as "could not load". A token that contains
// `-support-` is a support person's: the list gives it the id, the name and the status only, as the real route
// does. Like the real routes, a write answers 201 for a new tenant and 200 for the same tenant again, and
// `recorded: true`. Only the routes the console flows in the browser tests use are here; every other `/platform`
// route is a 404.

export const OPERATOR_LIVE_PREFIX = 'e2e-operator-live-';

type Binding = { directoryId: string; status: 'pending' | 'verified' | 'revoked'; verifiedAt: string | null };
type Mapping = { groupObjectId: string; role: string; status: 'active' | 'retired' };
type Tenant = {
  id: string;
  displayName: string;
  legalName: string;
  organisationType: string;
  countryCode: string;
  timeZone: string;
  odsCode: string | null;
  status: 'provisioning' | 'active';
  host: string | null;
  createdAt: string;
  bindings: Binding[];
  roleMappings: Mapping[];
  directoryId: string | null;
  invitation?: { emailMasked: string; createdAt: string; expiresAt: string };
};

const stores = new Map<string, Map<string, Tenant>>();
const storeOf = (token: string) => {
  let store = stores.get(token);
  if (store === undefined) {
    store = new Map();
    stores.set(token, store);
  }
  return store;
};

const NOT_FOUND = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'The requested resource was not found.' }] };
const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MAPPABLE = ['advisor', 'clinical', 'lead', 'owner', 'exec', 'audit'];

function send(response: ServerResponse, status: number, body: unknown) {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }).end(JSON.stringify(body));
}

const bearer = (request: IncomingMessage): string | undefined => /^Bearer (.+)$/.exec(request.headers.authorization ?? '')?.[1];

async function bodyOf(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(chunk as Buffer);
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}') as Record<string, unknown>;
  } catch {
    return {};
  }
}

const listed = (t: Tenant) => ({ id: t.id, displayName: t.displayName, status: t.status, organisationType: t.organisationType, host: t.host, activatedAt: null });

function detail(t: Tenant) {
  return {
    tenant: {
      id: t.id,
      displayName: t.displayName,
      legalName: t.legalName,
      organisationType: t.organisationType,
      countryCode: t.countryCode,
      timeZone: t.timeZone,
      odsCode: t.odsCode,
      status: t.status,
      epoch: 1,
      createdAt: t.createdAt,
      activatedAt: null,
      suspendedAt: null,
      suspendMode: null,
      suspendReason: null,
      offboardingStartedAt: null,
      offboardedAt: null,
      purgedAt: null,
      references: { dsa: null, dpia: null, dcb0160: null },
    },
    host: t.host,
    directoryId: t.directoryId,
    bindings: t.bindings,
    roleMappings: t.roleMappings,
    numbers: [],
    activation: { ready: false, blockers: ['Host set', 'Number tested'] },
  };
}

/** Answers the `/platform/...` routes for a live operator token and returns true; false for anything else. */
export async function handlePlatformRoute(request: IncomingMessage, response: ServerResponse, pathname: string): Promise<boolean> {
  const token = bearer(request);
  if (token === undefined || !token.startsWith(OPERATOR_LIVE_PREFIX)) return false;
  const support = token.includes('-support-');
  const store = storeOf(token);
  const get = request.method === 'GET';

  if (get && pathname === '/platform/session') {
    send(response, 200, {
      role: support ? 'support' : 'platform-operator',
      accountRef: 'ops-e2e00000000000000000000000000001',
      expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
      permissions: support ? ['tenants:list', 'support:request'] : ['tenants:list', 'tenants:read', 'tenants:provision', 'tenants:lifecycle', 'audit:read'],
    });
    return true;
  }
  if (get && pathname === '/platform/tenants') {
    const all = [...store.values()].sort((a, b) => a.id.localeCompare(b.id));
    send(response, 200, { tenants: support ? all.map(({ id, displayName, status }) => ({ id, displayName, status })) : all.map(listed) });
    return true;
  }
  const one = /^\/platform\/tenants\/([a-z0-9][a-z0-9-]{0,30})(\/directory\/verification|\/admin-consent|\/admin-consent-invitation)?$/.exec(pathname);
  if (one === null) return false;
  const id = one[1]!;
  if (support) {
    send(response, 404, NOT_FOUND);
    return true;
  }

  // The admin consent invitation (DEC-1316): the stand-in keeps the masked address only, as the real route does.
  if (one[2] === '/admin-consent' && get) {
    const found = store.get(id);
    const invite = found?.invitation;
    send(response, found === undefined ? 404 : 200, found === undefined ? NOT_FOUND : { invitation: invite === undefined ? null : { inviteId: 'inv-e2e', status: 'pending', consentedAt: null, reason: null, ...invite } });
    return true;
  }
  if (one[2] === '/admin-consent-invitation' && request.method === 'POST') {
    const body = await bodyOf(request);
    const found = store.get(id);
    const email = typeof body.email === 'string' ? /^([^@\s])[^@\s]*@([^@\s]+)$/.exec(body.email) : null;
    if (found === undefined || email === null) {
      send(response, found === undefined ? 404 : 422, found === undefined ? NOT_FOUND : { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] });
      return true;
    }
    const now = Date.now();
    found.invitation = { emailMasked: `${email[1]}***@${email[2]}`, createdAt: new Date(now).toISOString(), expiresAt: new Date(now + 7 * 86_400_000).toISOString() };
    send(response, 201, { invitation: { inviteId: 'inv-e2e', status: 'pending', consentedAt: null, reason: null, ...found.invitation }, recorded: true });
    return true;
  }

  if (get && one[2] === undefined) {
    const found = store.get(id);
    send(response, found === undefined ? 404 : 200, found === undefined ? NOT_FOUND : detail(found));
    return true;
  }

  if (request.method === 'PUT' && one[2] === undefined) {
    const body = await bodyOf(request);
    const directory = typeof body.directoryId === 'string' ? body.directoryId.toLowerCase() : null;
    const mappings = Array.isArray(body.roleMappings) ? (body.roleMappings as { groupObjectId?: unknown; role?: unknown }[]) : [];
    const badDirectory = directory !== null && !GUID.test(directory);
    const badMapping = mappings.some((m) => typeof m.groupObjectId !== 'string' || !GUID.test(m.groupObjectId.toLowerCase()) || typeof m.role !== 'string' || !MAPPABLE.includes(m.role));
    if (typeof body.displayName !== 'string' || typeof body.legalName !== 'string' || badDirectory || badMapping) {
      send(response, 422, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] });
      return true;
    }
    const existing = store.get(id);
    if (existing !== undefined) {
      send(response, 200, { tenantId: id, created: false, recorded: true });
      return true;
    }
    store.set(id, {
      id,
      displayName: body.displayName,
      legalName: body.legalName,
      organisationType: typeof body.organisationType === 'string' ? body.organisationType : 'other',
      countryCode: typeof body.countryCode === 'string' ? body.countryCode : 'GB',
      timeZone: typeof body.timeZone === 'string' ? body.timeZone : 'Europe/London',
      odsCode: typeof body.odsCode === 'string' ? body.odsCode : null,
      status: 'provisioning',
      host: null,
      createdAt: new Date().toISOString(),
      // A directory named at creation is saved as waiting; verifying it is a separate step.
      bindings: directory === null ? [] : [{ directoryId: directory, status: 'pending', verifiedAt: null }],
      roleMappings: mappings.map((m) => ({ groupObjectId: String(m.groupObjectId).toLowerCase(), role: String(m.role), status: 'active' as const })),
      directoryId: null,
    });
    send(response, 201, { tenantId: id, created: true, recorded: true });
    return true;
  }

  if (request.method === 'POST' && one[2] !== undefined) {
    const body = await bodyOf(request);
    const found = store.get(id);
    const waiting = found?.bindings.find((b) => b.directoryId === body.directoryId && b.status === 'pending');
    if (found === undefined || waiting === undefined) {
      send(response, 404, NOT_FOUND);
      return true;
    }
    waiting.status = 'verified';
    waiting.verifiedAt = new Date().toISOString();
    found.directoryId = waiting.directoryId;
    send(response, 200, { recorded: true });
    return true;
  }
  return false;
}
