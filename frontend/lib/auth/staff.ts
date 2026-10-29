import { SignJWT } from 'jose';
import { canAccess, isSamePathOnly, roleHome } from './access';
import type { Role } from './session';

// Staff sign-in rules that do not depend on the provider: which Entra app role
// is which DIUCS role, the back-end token the BFF mints, and where to go next.

export type StaffRole = 'advisor' | 'clinical' | 'lead' | 'owner' | 'exec' | 'support';

const ROLE_CLAIMS: ReadonlyMap<string, StaffRole> = new Map([
  ['DIUCS.Advisor', 'advisor'],
  ['DIUCS.Clinical', 'clinical'],
  ['DIUCS.Lead', 'lead'],
  ['DIUCS.Owner', 'owner'],
  ['DIUCS.Planning', 'exec'],
  ['DIUCS.Support', 'support'],
]);

// Several roles: the first of these the person holds.
const PRIORITY: readonly StaffRole[] = ['lead', 'clinical', 'advisor', 'owner', 'exec', 'support'];

/**
 * The DIUCS role for the Entra `roles` claim, or null when none maps. The support role is the
 * operator's own and is given only when `allowSupport` is true: a customer's directory
 * administrator can create any app role assignment in it, so it must not be able to create this.
 */
export function mapRoles(claim: unknown, options: { allowSupport?: boolean } = {}): StaffRole | null {
  if (!Array.isArray(claim)) return null;
  const held = new Set<StaffRole>();
  for (const value of claim) {
    if (typeof value !== 'string') continue;
    const role = ROLE_CLAIMS.get(value);
    if (role === undefined) continue;
    if (role === 'support' && options.allowSupport !== true) continue;
    held.add(role);
  }
  return PRIORITY.find((role) => held.has(role)) ?? null;
}

export const BACKEND_TOKEN_LIFETIME_SECONDS = 8 * 3600;

const SECRET_VARIABLE = 'BACKEND_JWT_SECRET';
const BASE64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
const BACKEND_MIN_SECRET_BYTES = 32; // the back end refuses less (bff_token.py)
const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// Tenant ids as the back end accepts them (application/tenancy.py TENANT_ID_PATTERN), and not a network.
const TENANT_ID = /^[a-z0-9][a-z0-9-]{1,30}$/;

export function isTenantId(value: string): boolean {
  return TENANT_ID.test(value) && !value.startsWith('net-');
}

export function isGuid(value: string): boolean {
  return GUID.test(value);
}

function backendSecret(): Uint8Array {
  // Read at call time, so a missing value fails the sign-in that needs it. The message names the
  // variable only, never its value.
  const value = process.env[SECRET_VARIABLE];
  const bytes = value && BASE64.test(value) ? Buffer.from(value, 'base64') : null;
  if (bytes === null || bytes.length < BACKEND_MIN_SECRET_BYTES) {
    throw new Error(`${SECRET_VARIABLE} must be set to at least 32 random bytes, base64 encoded`);
  }
  return new Uint8Array(bytes);
}

/** The instant the token expires, to the second, so the session never outlives its token. */
export function backendTokenExpiresAt(now: Date): Date {
  return new Date((Math.floor(now.getTime() / 1000) + BACKEND_TOKEN_LIFETIME_SECONDS) * 1000);
}

/**
 * The back-end bearer token (R02): HS256, `sub` the Entra object id, `role`, `services` (staff roles
 * see every service of their tenant, which R02 reads from the role, so the list is empty), `tid` the
 * DIUCS tenant the verified directory is bound to, and `exp` eight hours on. Never a name or an
 * email: nothing else is put in it.
 */
export async function mintBackendToken(
  identity: { oid: string; role: StaffRole; tenantId: string },
  now: Date = new Date(),
): Promise<string> {
  const key = backendSecret();
  if (!isGuid(identity.oid)) throw new Error('The object id is not a GUID');
  if (!isTenantId(identity.tenantId)) throw new Error('The tenant id is not valid');
  const issuedAt = Math.floor(now.getTime() / 1000);
  return new SignJWT({ role: identity.role, services: [], tid: identity.tenantId })
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .setSubject(identity.oid)
    .setIssuedAt(issuedAt)
    .setExpirationTime(issuedAt + BACKEND_TOKEN_LIFETIME_SECONDS)
    .sign(key);
}

/**
 * Where to go after signing in: `next` when it is a path on this site the role may open (and not the
 * sign-in page itself), otherwise the role's home.
 */
export function safeNext(next: string | null | undefined, role: Role): string {
  if (typeof next !== 'string' || !isSamePathOnly(next)) return roleHome(role);
  const path = next.replace(/[?#].*$/s, '');
  if (path.replace(/\/+$/, '').toLowerCase() === '/sign-in') return roleHome(role);
  return canAccess(role, path) ? next : roleHome(role);
}
