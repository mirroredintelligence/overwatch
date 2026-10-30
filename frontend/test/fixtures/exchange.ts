import { createHmac } from 'node:crypto';
import { decodeJwt } from 'jose';
import { DIRECTORY_A, DIRECTORY_B, DIRECTORY_PLATFORM, SIGN_IN_HOST } from '@/test/oidc/constants';

// A stand-in for the back end's token exchange (TEN-043, DEC-522 to DEC-526): `POST /auth/token`
// and `POST /auth/device-token`. It is a stand-in, not the back end: it answers the shapes the
// route module documents, from a table of grants, and signs its tokens with a key of its own. The
// front end never verifies them (it cannot: it holds no signing secret), so the key matters only
// to a test that wants to show that no secret is shared.
//
// The real exchange decides the role from the tenant's own mapping of directory groups. The
// stand-in decides it from the `roles` claim of the ID token it is given, which is how the fake
// Entra names a person's access, and only when the HOST has the directory bound: a member of
// another tenant's directory gets the one refusal.

export const STAND_IN_KEY = 'stand-in-signing-key-for-tests-only';
/** The tenant id the stand-in gives the tenant that owns a host: a valid tenant id (letters, digits, hyphens). */
export function tenantOfHost(host: string): string {
  return `tenant-of-${host.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`.slice(0, 31).replace(/-+$/, '');
}

export const REFUSED_TEXT = 'Your account does not have access.';
export const STAFF_LIFETIME_SECONDS = 8 * 3600;
export const WALL_LIFETIME_SECONDS = 3600;

/** The hosts a tenant is reached on, and the directory each has bound. */
export const GRANTS: Record<string, string[]> = {
  [SIGN_IN_HOST]: [DIRECTORY_A],
  'trust-b.example.test': [DIRECTORY_B],
  // One directory bound to two tenants: each host gives its own tenant's answer.
  'shared.example.test': [DIRECTORY_A, DIRECTORY_B],
};

const ROLE_BY_APP_ROLE: Record<string, string> = {
  'DIUCS.Advisor': 'advisor',
  'DIUCS.Clinical': 'clinical',
  'DIUCS.Lead': 'lead',
  'DIUCS.Owner': 'owner',
  'DIUCS.Planning': 'exec',
  'DIUCS.Audit': 'audit',
  'DIUCS.TenantAdmin': 'tenant-admin',
  'DIUCS.NetworkAdmin': 'network-admin',
};
const PRIORITY = ['tenant-admin', 'network-admin', 'lead', 'clinical', 'advisor', 'owner', 'exec', 'audit'];

export type ExchangeReply = { status: number; body: unknown };

/** A device token a paired screen holds, and the screen it names. */
export const DEVICES: Record<string, string> = {
  'device-token-for-screen-one': 'dev-screen-one',
  'device-token-for-screen-two': 'dev-screen-two',
};

function b64(value: unknown): string {
  return Buffer.from(JSON.stringify(value)).toString('base64url');
}

/** A token shaped as the back end's: three parts, `sub`, `role`, `aud`, `iat`, `exp`. */
export function standInToken(claims: Record<string, unknown>): string {
  const head = b64({ alg: 'HS256', typ: 'JWT' });
  const body = b64(claims);
  const signature = createHmac('sha256', STAND_IN_KEY).update(`${head}.${body}`).digest('base64url');
  return `${head}.${body}.${signature}`;
}

function iso(seconds: number): string {
  return new Date(seconds * 1000).toISOString().replace('.000Z', 'Z');
}

function subjectOf(host: string, directory: string, oid: string): string {
  const digest = createHmac('sha256', STAND_IN_KEY).update(`subject|${host}|${directory}|${oid}`).digest('hex');
  return `stf-${digest.slice(0, 32)}`;
}

function refused(): ExchangeReply {
  return {
    status: 403,
    body: { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'forbidden', diagnostics: REFUSED_TEXT }] },
  };
}

function notFound(): ExchangeReply {
  return {
    status: 404,
    body: { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'Not found.' }] },
  };
}

function badRequest(): ExchangeReply {
  return { status: 400, body: { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] } };
}

/** `POST /auth/token` for a request addressed to `host`, with the body the BFF sent. */
export function staffExchange(
  host: string | null,
  body: unknown,
  now: Date = new Date(),
  grants: Record<string, string[]> = GRANTS,
): ExchangeReply {
  const keys = typeof body === 'object' && body !== null ? Object.keys(body) : [];
  const idToken = (body as { idToken?: unknown } | null)?.idToken;
  if (keys.length !== 1 || typeof idToken !== 'string' || idToken === '') return badRequest();
  const directories = host === null ? undefined : grants[host];
  if (directories === undefined) return notFound();
  let claims: Record<string, unknown>;
  try {
    claims = decodeJwt(idToken);
  } catch {
    return refused();
  }
  const directory = typeof claims.tid === 'string' ? claims.tid : '';
  const oid = typeof claims.oid === 'string' ? claims.oid : '';
  if (!directories.includes(directory)) return refused();
  const held = (Array.isArray(claims.roles) ? claims.roles : []).flatMap((r) => ROLE_BY_APP_ROLE[String(r)] ?? []);
  const role = PRIORITY.find((candidate) => held.includes(candidate));
  if (role === undefined) return refused();
  const issuedAt = Math.floor(now.getTime() / 1000);
  const expires = issuedAt + STAFF_LIFETIME_SECONDS;
  const token = standInToken({
    sub: subjectOf(host as string, directory, oid),
    role,
    services: [],
    tenant: tenantOfHost(host as string),
    epoch: 1,
    aud: 'diucs-api',
    iat: issuedAt,
    exp: expires,
  });
  return { status: 200, body: { token, expiresAt: iso(expires), role } };
}

/** `POST /auth/device-token` for a request addressed to `host`, with `Authorization: Bearer <device token>`. */
export function deviceExchange(
  host: string | null,
  authorization: string | null,
  body: unknown,
  now: Date = new Date(),
  grants: Record<string, string[]> = GRANTS,
): ExchangeReply {
  const keys = typeof body === 'object' && body !== null ? Object.keys(body) : [-1];
  if (keys.length !== 0) return badRequest();
  const deviceToken = /^Bearer (.+)$/.exec(authorization ?? '')?.[1];
  const device = deviceToken === undefined ? undefined : DEVICES[deviceToken];
  if (host === null || grants[host] === undefined || device === undefined) return notFound();
  const issuedAt = Math.floor(now.getTime() / 1000);
  const expires = issuedAt + WALL_LIFETIME_SECONDS;
  const token = standInToken({
    sub: device,
    role: 'wall',
    services: [],
    tenant: tenantOfHost(host),
    epoch: 1,
    aud: 'diucs-api',
    iat: issuedAt,
    exp: expires,
  });
  return { status: 200, body: { token, expiresAt: iso(expires), role: 'wall' } };
}

const OPERATOR_ROLE_BY_APP_ROLE: Record<string, string> = {
  'DIUCS.PlatformOperator': 'platform-operator',
  'DIUCS.Support': 'support',
};
const OPERATOR_PRIORITY = ['platform-operator', 'support'];
export const OPERATOR_LIFETIME_SECONDS = 3600;

/** `POST /auth/operator-token`: the operator directory only, no host and no tenant (TEN-043, DEC-1000). */
export function operatorExchange(body: unknown, directory: string = DIRECTORY_PLATFORM, now: Date = new Date()): ExchangeReply {
  const keys = typeof body === 'object' && body !== null ? Object.keys(body) : [];
  const idToken = (body as { idToken?: unknown } | null)?.idToken;
  if (keys.length !== 1 || typeof idToken !== 'string' || idToken === '') return badRequest();
  let claims: Record<string, unknown>;
  try {
    claims = decodeJwt(idToken);
  } catch {
    return refused();
  }
  const oid = typeof claims.oid === 'string' ? claims.oid : '';
  if (claims.tid !== directory) return refused();
  const held = (Array.isArray(claims.roles) ? claims.roles : []).flatMap((r) => OPERATOR_ROLE_BY_APP_ROLE[String(r)] ?? []);
  const role = OPERATOR_PRIORITY.find((candidate) => held.includes(candidate));
  if (role === undefined) return refused();
  const issuedAt = Math.floor(now.getTime() / 1000);
  const expires = issuedAt + OPERATOR_LIFETIME_SECONDS;
  const digest = createHmac('sha256', STAND_IN_KEY).update(`operator|${oid}`).digest('hex');
  const token = standInToken({ sub: `ops-${digest.slice(0, 32)}`, role, aud: 'diucs-ops', iat: issuedAt, exp: expires });
  return { status: 200, body: { token, expiresAt: iso(expires), role } };
}
