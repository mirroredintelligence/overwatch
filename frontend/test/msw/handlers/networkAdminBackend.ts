import { http, HttpResponse } from 'msw';
import { claimsOf } from '@/test/backendToken';
import { GRANTS, LISTINGS, MEMBER_NETWORKS, MEMBERS, OWNER_NETWORKS, PROJECTION, SHARING } from '@/test/fixtures/network-admin-shapes';
import { TENANTS } from '@/test/tenants';

// A stand-in for the back end's network and grant administration routes (routes_network_admin.py, TEN-079,
// and the sharing read of TEN-081), at the app ROOT. The answers are the fixtures the back end's own
// converters wrote (test/fixtures/network-admin-shapes.gen.py). Like the real routes it answers from the
// token only: tenant A owns the network; B is a member; C is in none. A role a route does not name, a
// network that is not the caller's and an unknown id are the one 404 with the same body, and the platform
// operator would be a 401. Every request is recorded with the claims of its token and its body.

export const ADMIN_ROOT = 'http://backend.test';
export const NETWORK_ID = 'net-sample';
export const OWNER = TENANTS.A;
export const MEMBER = TENANTS.B;

export type SeenAdmin = { method: string; path: string; query: string; role: string; tenant: string; body: unknown; contentType: string | null };
export const seenAdmin: SeenAdmin[] = [];
export function resetAdminBackend(): void {
  seenAdmin.length = 0;
}

const NOT_FOUND = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'The requested resource was not found.' }] };
const CONFLICT = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict', diagnostics: 'A conflict.' }] };
const refuse = () => HttpResponse.json(NOT_FOUND, { status: 404, headers: { 'Cache-Control': 'no-store' } });
const NO_STORE = { 'Cache-Control': 'no-store' };

type Claims = { role: string; tenant: string };
function claimsFor(request: Request): Claims | null {
  const header = request.headers.get('authorization');
  const token = header === null ? undefined : /^Bearer (.+)$/.exec(header)?.[1];
  if (token === undefined || token.split('.').length !== 3) return null;
  try {
    const claims = claimsOf(token);
    return typeof claims.tenant === 'string' && typeof claims.role === 'string' ? { role: claims.role, tenant: claims.tenant } : null;
  } catch {
    return null;
  }
}

async function record(request: Request, claims: Claims | null): Promise<void> {
  const url = new URL(request.url);
  let body: unknown;
  try {
    body = await request.clone().json();
  } catch {
    body = undefined;
  }
  seenAdmin.push({
    method: request.method,
    path: url.pathname,
    query: url.search.slice(1),
    role: claims?.role ?? '',
    tenant: claims?.tenant ?? '',
    body,
    contentType: request.headers.get('content-type'),
  });
}

type Resolver = (arguments_: { request: Request; params: Record<string, string | readonly string[] | undefined> }) => Response | Promise<Response>;

/** A route for some roles. `owns` also requires the caller to be the owner of the named network. */
function route(roles: string[], answer: (request: Request, claims: Claims, params: Record<string, string>) => Response | Promise<Response>, owns = false): Resolver {
  return async ({ request, params }) => {
    const claims = claimsFor(request);
    await record(request, claims);
    if (claims === null) return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] }, { status: 401 });
    if (!roles.includes(claims.role)) return refuse();
    const plain: Record<string, string> = {};
    for (const [key, value] of Object.entries(params)) plain[key] = String(value);
    if (owns && (plain.id !== NETWORK_ID || claims.tenant !== OWNER.id)) return refuse();
    return answer(request, claims, plain);
  };
}

const ok = (body: unknown, status = 200) => HttpResponse.json(body as Record<string, unknown>, { status, headers: NO_STORE });

/** What a tenant sees of `GET /network-admin/networks`: the owner, a member, or nothing. */
function networksFor(claims: Claims) {
  if (claims.tenant === OWNER.id) return OWNER_NETWORKS;
  if (claims.tenant === MEMBER.id) return MEMBER_NETWORKS;
  return { networks: [] };
}

function grantsOf(claims: Claims) {
  const name = claims.tenant === OWNER.id ? 'Sample Area A' : claims.tenant === MEMBER.id ? 'Sample Area B' : null;
  return { grants: GRANTS.grants.filter((g) => g.organisation_name === name) };
}

const NA = ['network-admin'];
const TA = ['tenant-admin'];

export const adminBackendHandlers = [
  http.get(`${ADMIN_ROOT}/network-admin/networks`, route([...NA, ...TA], (_r, claims) => ok(networksFor(claims)))),
  http.get(`${ADMIN_ROOT}/network-admin/sharing`, route(TA, (_r, claims) => ok(claims.tenant === MEMBER.id ? SHARING : { allowlist: SHARING.allowlist, networks: [] }))),
  http.get(`${ADMIN_ROOT}/network-admin/network/:id/members`, route(NA, () => ok(MEMBERS), true)),
  http.post(
    `${ADMIN_ROOT}/network-admin/network/:id/members`,
    route(
      NA,
      async (request) => {
        const body = (await request.clone().json()) as { tenant_id?: string };
        if (body.tenant_id === 'sample-area-b') return HttpResponse.json(CONFLICT, { status: 409 });
        if (body.tenant_id !== 'sample-area-c') return refuse();
        return ok({ membership_id: 'mem-new', status: 'invited' }, 201);
      },
      true,
    ),
  ),
  http.post(`${ADMIN_ROOT}/network-admin/network/:id/members/:membership/remove`, route(NA, (_r, _c, p) => (p.membership === 'mem-a' ? ok({ status: 'removed', grants_lapsed: 2, listings_withdrawn: 1 }) : refuse()), true)),
  http.post(`${ADMIN_ROOT}/network-admin/network/:id/agreement`, route(NA, async (request) => ok({ agreement_version: ((await request.clone().json()) as { version: number }).version }), true)),
  http.get(`${ADMIN_ROOT}/network-admin/network/:id/projection`, route(NA, () => ok(PROJECTION), true)),
  http.get(`${ADMIN_ROOT}/network-admin/network/:id/grants`, route(NA, () => ok(GRANTS), true)),
  http.get(`${ADMIN_ROOT}/network-admin/grants`, route(TA, (_r, claims) => ok(grantsOf(claims)))),
  http.post(`${ADMIN_ROOT}/network-admin/grants`, route(TA, async (request, claims) => (claims.tenant === MEMBER.id && ((await request.clone().json()) as { network_id?: string }).network_id === NETWORK_ID ? ok({ id: 'grant-new', status: 'proposed' }, 201) : refuse()))),
  http.post(`${ADMIN_ROOT}/network-admin/grants/:grant/approve`, route([...NA, ...TA], (_r, claims, p) => (p.grant.startsWith('grant-') ? ok({ effective: claims.role === 'network-admin' && p.grant === 'grant-1' }) : refuse()))),
  http.post(`${ADMIN_ROOT}/network-admin/grants/:grant/decline`, route([...NA, ...TA], (_r, _c, p) => (p.grant.startsWith('grant-') ? ok({ status: 'declined' }) : refuse()))),
  http.post(`${ADMIN_ROOT}/network-admin/grants/:grant/end`, route(TA, (_r, _c, p) => (p.grant.startsWith('grant-') ? ok({ status: 'ended' }) : refuse()))),
  http.get(`${ADMIN_ROOT}/network-admin/network/:id/listings`, route(NA, () => ok(LISTINGS), true)),
  ...(['admit', 'reinstate', 'decline', 'suspend'] as const).map((action) =>
    http.post(
      `${ADMIN_ROOT}/network-admin/network/:id/listings/:listing/${action}`,
      route(
        NA,
        async (request, _c, p) => {
          if (!p.listing.startsWith('lst-')) return refuse();
          if (action === 'decline' || action === 'suspend') {
            const body = (await request.clone().json()) as { reason?: string };
            if (typeof body.reason !== 'string') return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] }, { status: 400 });
          }
          return ok({ status: 'done' });
        },
        true,
      ),
    ),
  ),
  http.post(`${ADMIN_ROOT}/network-admin/network/:id/leave`, route(TA, (_r, claims, p) => (claims.tenant === MEMBER.id && p.id === NETWORK_ID ? ok({ status: 'left', grants_lapsed: 1, listings_withdrawn: 0 }) : refuse()))),
  http.post(`${ADMIN_ROOT}/network-admin/memberships/:membership/accept`, route(TA, (_r, claims, p) => (claims.tenant === MEMBER.id && p.membership === 'mem-a' ? ok({ status: 'active' }) : refuse()))),
];
