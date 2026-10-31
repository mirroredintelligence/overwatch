import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { claimsOf } from '@/test/backendToken';
import {
  BOARD_BODY,
  CRITERIA_BODY,
  DIRECTORY_BODY,
  DIRECTORY_HISTORY_BODY,
  NETWORKS_BODY,
  PHONES_BODY,
  SYSTEM_NOW_BODY,
  WEEK_BODY,
} from '@/test/fixtures/network';
import { NETWORK } from '@/test/tenants';

// A stand-in for the back end's network routes (routes_network.py, routes_network_views.py), at the
// app ROOT (not under /fhir). Like the real routes it answers from the token only: a tenant that is
// not an active member, a role that never sees a network, a network outside the claim and an unknown
// network are all the one 404, with the same body. It records every request it sees.

export const NETWORK_ROOT = 'http://backend.test';

export type SeenNetworkRequest = { method: string; path: string; query: string; authorised: boolean };
export const seenNetwork: SeenNetworkRequest[] = [];

export function resetNetworkBackend(): void {
  seenNetwork.length = 0;
}

const VIEW_ROLES = ['advisor', 'clinical', 'lead', 'owner', 'exec'];
const WEEK_ROLES = ['exec', 'lead'];
const NOT_FOUND = {
  resourceType: 'OperationOutcome',
  issue: [{ severity: 'error', code: 'not-found', diagnostics: 'The requested resource was not found.' }],
};

function claimsFor(request: Request): { tenant: string; role: string } | null {
  const header = request.headers.get('authorization');
  const token = header === null ? undefined : /^Bearer (.+)$/.exec(header)?.[1];
  if (token === undefined || token.split('.').length !== 3) return null;
  try {
    const claims = claimsOf(token);
    return typeof claims.tenant === 'string' && typeof claims.role === 'string' ? { tenant: claims.tenant, role: claims.role } : null;
  } catch {
    return null;
  }
}

const refuse = () => HttpResponse.json(NOT_FOUND, { status: 404 });

function record(request: Request): void {
  const url = new URL(request.url);
  seenNetwork.push({ method: request.method, path: url.pathname, query: url.search.slice(1), authorised: claimsFor(request) !== null });
}

/** A route of one network: the viewer must be a member with a role that sees a network. */
function networkRoute(body: (request: Request, id: string) => Record<string, unknown>, roles: string[] = VIEW_ROLES): HttpResponseResolver {
  return ({ request, params }) => {
    record(request);
    const claims = claimsFor(request);
    if (claims === null) return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] }, { status: 401 });
    const id = String(params.id);
    if (!roles.includes(claims.role) || id !== NETWORK.id || !NETWORK.memberIds.includes(claims.tenant)) return refuse();
    return HttpResponse.json(body(request, id));
  };
}

const networks: HttpResponseResolver = ({ request }) => {
  record(request);
  const claims = claimsFor(request);
  if (claims === null) return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] }, { status: 401 });
  if (!VIEW_ROLES.includes(claims.role)) return refuse();
  return HttpResponse.json(NETWORK.memberIds.includes(claims.tenant) ? NETWORKS_BODY : { networks: [] });
};

export const networkHandlers = [
  http.get(`${NETWORK_ROOT}/networks`, networks),
  http.get(`${NETWORK_ROOT}/network/:id/board`, networkRoute(() => BOARD_BODY)),
  http.get(
    `${NETWORK_ROOT}/network/:id/directory`,
    networkRoute((request) => (new URL(request.url).searchParams.get('history') === 'true' ? DIRECTORY_HISTORY_BODY : DIRECTORY_BODY)),
  ),
  http.get(
    `${NETWORK_ROOT}/network/:id/criteria`,
    networkRoute((request) =>
      new URL(request.url).searchParams.get('history') === 'true' ? { ...CRITERIA_BODY, entries: [] } : CRITERIA_BODY,
    ),
  ),
  http.get(`${NETWORK_ROOT}/network/:id/system-now`, networkRoute(() => SYSTEM_NOW_BODY)),
  http.get(`${NETWORK_ROOT}/network/:id/phones`, networkRoute(() => PHONES_BODY)),
  http.get(`${NETWORK_ROOT}/network/:id/week`, networkRoute(() => WEEK_BODY, WEEK_ROLES)),
];
