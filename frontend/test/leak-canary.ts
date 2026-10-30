import { claimsOf } from '@/test/backendToken';
import { NETWORK } from '@/test/tenants';
import { namesTenantInput } from '@/lib/tenant/inputNames';

// The leak canary (TEN-047, audit D 7.3). It looks at every call the front end makes to the back end,
// in every test (test/setup.ts installs it and asserts it after each test), and records a leak when a
// call could cross a tenant boundary:
//
//   tenant-mismatch     the token is another tenant's than the one the test signed in as
//   tenant-header       a header names a tenant, scope or network (X-Tenant-Id and the like)
//   tenant-query        a query key names a tenant, scope or network
//   link-bearer         a link call carries an Authorization header (a link has no session)
//   network-non-member  a network route is called with a token of a tenant that is not a member
//   no-token            a call to the tenant API with no token
//   pre-session-bearer  a pre-session identity call (a phone with no session: text code, PIN, new
//                       phone) carries an Authorization header: its tenant is the host's, nothing else
//   pre-session-host    such a call does not carry a Host that names a tenant (none, or the back end's own)
//   bad-audience        a token for another audience (an operator token at the tenant API)
//
// A test says which tenants it signs in as by building a session or request with `sessionFor` and
// `requestAs` (test/requests.ts), which call `canary.expect`. A token the canary cannot read (the
// opaque test tokens of older tests) is judged on the other rules only. Nothing in a leak is a token,
// a cookie or a host: a rule word, the method and the path.

const BACKEND_ORIGINS: ReadonlySet<string> = new Set(['http://backend.test']);
const HEADER_NAME = /^(x-)?(tenant|scope|network|source-tenant)/i;
// Calls that have no token by design: the token exchanges, the public profile, the link pages and a
// wall screen's pairing (the screen has no session yet; its secret is a header).
const TOKENLESS_PATH = /^\/(auth|public|links)(\/|$)|^\/screens\/pairing(\/|$)/;
const LINK_PATH = /^\/links(\/|$)/;
// The identity routes a phone calls before it has a session. The back end reads the tenant from the
// Host the request was addressed to and takes no token; `push-subscription` and `sign-out-everywhere`
// are not here because they carry the signed-in person's token like every other route.
const PRE_SESSION_PATH =
  /^\/identity\/(?:code|pin|new-phone|device\/code|registration\/code|registration\/session|invitation|session-token|channel|invitations\/[^/]+\/code)(?:\/verify)?$|^\/identity\/status$|^\/invitations\/[^/]+$/;
const NETWORK_PATH = /^\/(?:fhir\/)?network\/([^/]+)(?:\/|$)/;
const STAFF_AUDIENCE = 'diucs-api';

export type LeakRule =
  | 'tenant-mismatch'
  | 'tenant-header'
  | 'tenant-query'
  | 'link-bearer'
  | 'network-non-member'
  | 'no-token'
  | 'pre-session-bearer'
  | 'pre-session-host'
  | 'bad-audience';

export type Leak = { rule: LeakRule; method: string; url: string };
export type UpstreamRequest = { method: string; url: string; headers: Headers };

function bearerOf(headers: Headers): string | null {
  const value = headers.get('authorization');
  const match = value === null ? null : /^Bearer (.+)$/.exec(value);
  return match?.[1] ?? null;
}

/** The claims of a token the canary can read, or null for an opaque one. */
function readable(token: string): { tenant?: string; aud?: string } | null {
  if (token.split('.').length !== 3) return null;
  try {
    const claims = claimsOf(token);
    return { tenant: typeof claims.tenant === 'string' ? claims.tenant : undefined, aud: typeof claims.aud === 'string' ? claims.aud : undefined };
  } catch {
    return null;
  }
}

/** The leaks in one call to the back end. Empty for a call to anywhere else. */
export function inspectUpstream(request: UpstreamRequest, expected: ReadonlySet<string>): Leak[] {
  let url: URL;
  try {
    url = new URL(request.url);
  } catch {
    return [];
  }
  if (!BACKEND_ORIGINS.has(url.origin)) return [];

  const found: LeakRule[] = [];
  const here = { method: request.method.toUpperCase(), url: url.pathname };

  for (const name of request.headers.keys()) {
    if (HEADER_NAME.test(name)) {
      found.push('tenant-header');
      break;
    }
  }
  for (const key of url.searchParams.keys()) {
    if (namesTenantInput(key)) {
      found.push('tenant-query');
      break;
    }
  }

  const token = bearerOf(request.headers);
  if (LINK_PATH.test(url.pathname)) {
    if (token !== null) found.push('link-bearer');
  } else if (PRE_SESSION_PATH.test(url.pathname)) {
    if (request.headers.has('authorization')) found.push('pre-session-bearer');
    const host = request.headers.get('host');
    if (host === null || host.toLowerCase() === url.host.toLowerCase()) found.push('pre-session-host');
  } else if (!TOKENLESS_PATH.test(url.pathname)) {
    if (token === null) {
      found.push('no-token');
    } else {
      const claims = readable(token);
      if (claims !== null) {
        if (claims.aud !== STAFF_AUDIENCE) found.push('bad-audience');
        if (claims.tenant !== undefined && expected.size > 0 && !expected.has(claims.tenant)) found.push('tenant-mismatch');
        const network = NETWORK_PATH.exec(url.pathname);
        if (network !== null && (claims.tenant === undefined || !NETWORK.memberIds.includes(claims.tenant))) {
          found.push('network-non-member');
        }
      }
    }
  }
  return found.map((rule) => ({ rule, ...here }));
}

const expectedTenants = new Set<string>();
const recorded: Leak[] = [];

export const canary = {
  /** The test signs in as this tenant: a token of any other tenant on a call is a leak. */
  expect(tenantId: string): void {
    expectedTenants.add(tenantId);
  },
  expected(): ReadonlySet<string> {
    return new Set(expectedTenants);
  },
  record(leaks: Leak[]): void {
    recorded.push(...leaks);
  },
  leaks(): Leak[] {
    return [...recorded];
  },
  /** Throws, naming each leak by rule, method and path, when any call leaked. */
  assertClean(): void {
    if (recorded.length === 0) return;
    const lines = recorded.map((leak) => `${leak.rule}: ${leak.method} ${leak.url}`);
    throw new Error(`The leak canary saw ${recorded.length} call(s) that could cross a tenant:\n${lines.join('\n')}`);
  },
  reset(): void {
    expectedTenants.clear();
    recorded.length = 0;
  },
};

type EventSource = {
  events: { on(event: 'request:start', listener: (arguments_: { request: Request }) => void): unknown };
};

/** Watches every request the MSW server sees (so also the ones no handler answers). */
export function installLeakCanary(server: EventSource): void {
  server.events.on('request:start', ({ request }) => {
    canary.record(inspectUpstream({ method: request.method, url: request.url, headers: request.headers }, expectedTenants));
  });
}
