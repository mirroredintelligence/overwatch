import { BackendCallError, callBackend } from '@/lib/fhir/hostCall';
import { STAFF_ROLES, type Role } from './session';
import { readIssuedToken } from './tokenClaims';

// Staff sign-in, step two: the person's verified identity token goes to the back end, and the back
// end answers with the tenant-bound token it signed itself (TEN-043, DEC-134 item 2, DEC-522). The
// front end holds no signing secret and mints nothing. The tenant is the HOST the person signed in
// on and nothing else: the call carries the host as its Host header, and the body carries the identity
// token alone (no tenant, role, audience or directory). The back end checks that the directory is the
// tenant's verified binding and takes the role from the tenant's own mapping.
//
// A failure is one of four words and carries nothing else: no token, host or tenant.

export type ExchangeFailure = 'refused' | 'not-found' | 'unavailable' | 'bad-answer';

export class ExchangeFailed extends Error {
  readonly reason: ExchangeFailure;

  constructor(reason: ExchangeFailure) {
    super('The token exchange failed.');
    this.name = 'ExchangeFailed';
    this.reason = reason;
  }
}

/** What the session is made of. */
export type StaffGrant = {
  role: Role;
  tenantId: string;
  sub: string;
  services: string[];
  backendToken: string;
  /** ISO 8601 instant, the back end's own expiry. */
  expiresAt: string;
};

const EXCHANGE_PATH = '/auth/token';
const MAX_CREDENTIAL_LENGTH = 8192;
// The back end's token and its stated expiry are the same instant, to the second; two seconds covers
// rounding and nothing more.
const EXPIRY_TOLERANCE_MS = 2000;

function isStaffRole(value: unknown): value is Role {
  return typeof value === 'string' && (STAFF_ROLES as readonly string[]).includes(value);
}

export async function exchangeStaffToken(
  idToken: string,
  host: string | null,
  now: Date = new Date(),
): Promise<StaffGrant> {
  if (typeof idToken !== 'string' || idToken.trim().length === 0 || idToken.length > MAX_CREDENTIAL_LENGTH) {
    throw new ExchangeFailed('refused');
  }

  let reply;
  try {
    reply = await callBackend({ method: 'POST', path: EXCHANGE_PATH, host, body: { idToken } });
  } catch (error) {
    if (error instanceof BackendCallError) throw new ExchangeFailed('unavailable');
    throw error;
  }

  if (reply.status === 403) throw new ExchangeFailed('refused');
  if (reply.status === 404) throw new ExchangeFailed('not-found');
  if (reply.status !== 200) throw new ExchangeFailed('unavailable');

  const body = typeof reply.body === 'object' && reply.body !== null && !Array.isArray(reply.body) ? (reply.body as Record<string, unknown>) : null;
  if (body === null) throw new ExchangeFailed('bad-answer');
  const { token, expiresAt, role } = body;
  if (!isStaffRole(role) || typeof token !== 'string' || typeof expiresAt !== 'string') throw new ExchangeFailed('bad-answer');

  const claims = readIssuedToken(token, now);
  if (claims === null || claims.role !== role) throw new ExchangeFailed('bad-answer');
  const expiresMs = Date.parse(expiresAt);
  if (Number.isNaN(expiresMs) || expiresMs <= now.getTime()) throw new ExchangeFailed('bad-answer');
  if (Math.abs(expiresMs - claims.exp * 1000) > EXPIRY_TOLERANCE_MS) throw new ExchangeFailed('bad-answer');

  return {
    role,
    tenantId: claims.tenant,
    sub: claims.sub,
    services: claims.services,
    backendToken: token,
    expiresAt,
  };
}
