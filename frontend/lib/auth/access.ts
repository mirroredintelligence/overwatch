import type { Role } from './session';

// Which role may open which page, and what a safe "where to go next" is. The proxy
// (proxy.ts) and the sign-in both read this one table, so they cannot disagree.

const PREFIX_ROLES: ReadonlyMap<string, readonly Role[]> = new Map([
  ['advisor', ['advisor']], // includes /advisor/case; a lead does not work a call (DEC-860)
  ['clinical', ['clinical']],
  ['lead', ['lead']],
  ['owner', ['owner', 'clinical']],
  // The criteria pages sit at /criteria/<service> (route group (owner)). The back end decides, per call,
  // which of these roles may approve or change; the page may be opened by all three (DEC-700).
  ['criteria', ['owner', 'clinical', 'lead']],
  ['planning', ['exec', 'lead']],
  // The network pages (TEN-068): the roles that see a network. The back end decides again, per call.
  ['network', ['advisor', 'clinical', 'lead', 'owner', 'exec']],
  ['console', ['support']],
  // The tenant administrator's pages (TEN-076): the role the back end gives a tenant's administrator.
  ['admin', ['tenant-admin']],
  // The network administrator's pages (TEN-080): the owner of a network. The back end decides again on
  // every call, and which network is the registry's answer, never the browser's.
  ['network-admin', ['network-admin']],
  // The operator console is another door with its own session (lib/operator): no tenant role opens it.
  ['operator', []],
]);

const HOMES: Readonly<Partial<Record<Role, string>>> = {
  advisor: '/advisor',
  clinical: '/clinical',
  lead: '/lead',
  owner: '/owner/criteria',
  exec: '/planning',
  support: '/console',
  'tenant-admin': '/admin',
  'network-admin': '/network-admin',
};

const FALLBACK_HOME = '/';
const NEXT_MAX_LENGTH = 2000;

/** The path as the router sees it: decoded, dot segments resolved, empty segments dropped. */
function segmentsOf(pathname: string): string[] | null {
  let decoded: string;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  const segments: string[] = [];
  for (const part of decoded.split('/')) {
    if (part === '' || part === '.') continue;
    if (part === '..') segments.pop();
    else segments.push(part);
  }
  return segments;
}

/**
 * The roles that may open a path, or null when the path is not guarded. A path that cannot be
 * decoded is guarded for nobody: fail closed. Matching is on the first path segment and ignores
 * case, so `/Lead` and `/%6Cead` are guarded like `/lead`.
 */
export function rolesFor(pathname: string): readonly Role[] | null {
  const segments = segmentsOf(pathname);
  if (segments === null) return [];
  return PREFIX_ROLES.get(segments[0]?.toLowerCase() ?? '') ?? null;
}

export function canAccess(role: Role, pathname: string): boolean {
  const allowed = rolesFor(pathname);
  return allowed === null || allowed.includes(role);
}

export function roleHome(role: Role): string {
  return HOMES[role] ?? FALLBACK_HOME;
}

// Characters a path, query and fragment may hold without escaping (RFC 3986), plus the percent sign.
// No quote, angle bracket, space, backslash or control character: a `next` that holds one is dropped,
// so it can never break out of the attribute or the address it is put in.
const PATH_CHARACTERS = /^[A-Za-z0-9\-._~!$&'()*+,;=:@%/?#]+$/;

/**
 * True for a path on this site and nothing else: it starts with one slash and no second slash
 * (a backslash is not in the character set), holds only URL-safe characters (a browser drops a tab
 * or newline, so `/\t/evil` would otherwise become `//evil`), and is not absurdly long.
 */
export function isSamePathOnly(value: string): boolean {
  if (value.length === 0 || value.length > NEXT_MAX_LENGTH) return false;
  if (value[0] !== '/' || value[1] === '/') return false;
  return PATH_CHARACTERS.test(value);
}
