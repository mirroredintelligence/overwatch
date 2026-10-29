import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { createRemoteJWKSet, errors, jwtVerify } from 'jose';
import { isGuid, isTenantId } from './staff';

// OpenID Connect against Microsoft Entra ID: the authorisation code flow with PKCE (S256),
// done here with `jose` and `fetch` and not with Auth.js (DEC-172). Nothing in this file logs,
// and every refusal is one of a fixed list of reasons that holds no token, code or claim.

/** One Entra directory and the DIUCS tenant it is bound to (W09 tenancy amendment). */
export type Binding = {
  directoryId: string;
  tenantId: string;
  /** The operator's own directory: the only one whose `DIUCS.Support` role is honoured. */
  platform: boolean;
};

export type EntraConfig = {
  clientId: string;
  clientSecret: string;
  /** Scheme and host of the Entra authority, no path. */
  authorityHost: string;
  /** This site's own address, from configuration, never from a request. */
  publicUrl: string;
  bindings: Binding[];
};

export type Transaction = { state: string; nonce: string; verifier: string; next: string };

export type Identity = {
  oid: string;
  directoryId: string;
  roles: unknown;
  binding: Binding;
};

export const REFUSALS = [
  'transaction',
  'provider-error',
  'state',
  'token-exchange',
  'bad-token',
  'keys-unavailable',
  'expired',
  'not-yet-valid',
  'wrong-audience',
  'wrong-issuer',
  'nonce',
  'bad-claims',
  'unbound-directory',
] as const;
export type Refusal = (typeof REFUSALS)[number];

/** A sign-in that must not go on. The message is fixed: it never repeats a token, a code or a claim. */
export class SignInRefused extends Error {
  readonly reason: Refusal;
  constructor(reason: Refusal) {
    super('sign-in refused');
    this.name = 'SignInRefused';
    this.reason = reason;
  }
}

const DEFAULT_AUTHORITY_HOST = 'https://login.microsoftonline.com';
const CALLBACK_PATH = '/api/bff/auth/entra/callback';
const CLOCK_TOLERANCE_SECONDS = 60;
const REQUEST_TIMEOUT_MS = 10_000;
const KEYS_TIMEOUT_MS = 5_000;
const KEYS_COOLDOWN_MS = 30_000;
const KEYS_MAX_AGE_MS = 3_600_000;
const ID_TOKEN_MAX_LENGTH = 8192;
const SHARED_AUTHORITY = 'organizations';

type Env = Record<string, string | undefined>;

function setting(env: Env, name: string): string {
  const value = env[name];
  if (!value) throw new Error(`${name} is not set`);
  return value;
}

// The message names the variable only, never the value.
function origin(env: Env, name: string, value: string): string {
  const production = env.NODE_ENV === 'production';
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${name} is not an address`);
  }
  const secure = url.protocol === 'https:';
  if (!secure && (production || url.protocol !== 'http:')) throw new Error(`${name} must be an https address`);
  if (url.pathname !== '/' || url.search || url.hash || url.username || url.password) {
    throw new Error(`${name} must be a scheme and host only`);
  }
  return url.origin;
}

function parseBindings(text: string): Binding[] {
  const fail = () => new Error('DIUCS_ENTRA_BINDINGS must be a list of { directoryId, tenantId, platform? }');
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw fail();
  }
  if (!Array.isArray(parsed) || parsed.length === 0) throw fail();
  const seen = new Set<string>();
  return parsed.map((entry: unknown): Binding => {
    if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) throw fail();
    const { directoryId, tenantId, platform, ...rest } = entry as Record<string, unknown>;
    if (Object.keys(rest).length > 0) throw fail();
    if (typeof directoryId !== 'string' || !isGuid(directoryId)) throw fail();
    if (typeof tenantId !== 'string' || !isTenantId(tenantId)) throw fail();
    if (platform !== undefined && typeof platform !== 'boolean') throw fail();
    const id = directoryId.toLowerCase();
    // One directory is one tenant: a second row for it would make the tenant ambiguous.
    if (seen.has(id)) throw fail();
    seen.add(id);
    return { directoryId: id, tenantId, platform: platform === true };
  });
}

/** Reads the settings at call time, so a missing value fails the request that needs it. */
export function loadEntraConfig(env: Env = process.env): EntraConfig {
  return {
    clientId: setting(env, 'ENTRA_CLIENT_ID'),
    clientSecret: setting(env, 'ENTRA_CLIENT_SECRET'),
    authorityHost: origin(env, 'ENTRA_AUTHORITY_HOST', env.ENTRA_AUTHORITY_HOST || DEFAULT_AUTHORITY_HOST),
    publicUrl: origin(env, 'DIUCS_PUBLIC_URL', setting(env, 'DIUCS_PUBLIC_URL')),
    bindings: parseBindings(setting(env, 'DIUCS_ENTRA_BINDINGS')),
  };
}

export function bindingFor(config: EntraConfig, directoryId: string): Binding | undefined {
  const wanted = directoryId.toLowerCase();
  return config.bindings.find((binding) => binding.directoryId === wanted);
}

// With one directory bound the sign-in asks that directory directly; with several it asks the
// shared `organizations` endpoint and the token's own directory is then checked against the list.
function authority(config: EntraConfig): string {
  const [only] = config.bindings;
  return config.bindings.length === 1 && only ? only.directoryId : SHARED_AUTHORITY;
}

function redirectUri(config: EntraConfig): string {
  return `${config.publicUrl}${CALLBACK_PATH}`;
}

function random(): string {
  return randomBytes(32).toString('base64url');
}

export function newTransaction(next: string): Transaction {
  return { state: random(), nonce: random(), verifier: random(), next };
}

export function authorizeUrl(config: EntraConfig, transaction: Transaction): URL {
  const url = new URL(`${config.authorityHost}/${authority(config)}/oauth2/v2.0/authorize`);
  const query = url.searchParams;
  query.set('client_id', config.clientId);
  query.set('response_type', 'code');
  query.set('redirect_uri', redirectUri(config));
  query.set('response_mode', 'query');
  // Only openid: no name, email or profile is asked for, so none is sent.
  query.set('scope', 'openid');
  query.set('state', transaction.state);
  query.set('nonce', transaction.nonce);
  query.set('code_challenge', createHash('sha256').update(transaction.verifier).digest('base64url'));
  query.set('code_challenge_method', 'S256');
  // A shared workstation must not sign the next person in silently as the last one.
  query.set('prompt', 'select_account');
  return url;
}

/** Redeems the code at the token endpoint and returns the ID token. Nothing else in the answer is read. */
export async function exchangeCode(config: EntraConfig, code: string, transaction: Transaction): Promise<string> {
  const refused = new SignInRefused('token-exchange');
  let body: unknown;
  try {
    const response = await fetch(`${config.authorityHost}/${authority(config)}/oauth2/v2.0/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code,
        redirect_uri: redirectUri(config),
        client_id: config.clientId,
        client_secret: config.clientSecret,
        code_verifier: transaction.verifier,
      }),
      redirect: 'error',
      cache: 'no-store',
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) throw refused;
    body = await response.json();
  } catch {
    throw refused;
  }
  const idToken = typeof body === 'object' && body !== null ? (body as Record<string, unknown>).id_token : undefined;
  if (typeof idToken !== 'string' || idToken.length === 0) throw refused;
  return idToken;
}

const keySets = new Map<string, ReturnType<typeof createRemoteJWKSet>>();

function keysFor(config: EntraConfig) {
  const address = `${config.authorityHost}/${authority(config)}/discovery/v2.0/keys`;
  let keys = keySets.get(address);
  if (!keys) {
    keys = createRemoteJWKSet(new URL(address), {
      timeoutDuration: KEYS_TIMEOUT_MS,
      cooldownDuration: KEYS_COOLDOWN_MS,
      cacheMaxAge: KEYS_MAX_AGE_MS,
    });
    keySets.set(address, keys);
  }
  return keys;
}

/** For tests: forget the signing keys fetched so far. */
export function resetKeyCache(): void {
  keySets.clear();
}

function sameText(a: string, b: string): boolean {
  const left = createHash('sha256').update(a).digest();
  const right = createHash('sha256').update(b).digest();
  return timingSafeEqual(left, right);
}

function refusalFor(error: unknown): SignInRefused {
  if (error instanceof errors.JWTExpired) return new SignInRefused('expired');
  if (error instanceof errors.JWTClaimValidationFailed) {
    if (error.claim === 'aud') return new SignInRefused('wrong-audience');
    if (error.claim === 'nbf') return new SignInRefused('not-yet-valid');
    return new SignInRefused('bad-claims');
  }
  // The key set could not be had (a timeout, an answer that was not the keys, no network).
  if (error instanceof errors.JWKSTimeout || (error instanceof errors.JOSEError && error.code === 'ERR_JOSE_GENERIC')) {
    return new SignInRefused('keys-unavailable');
  }
  // Anything else is a token that is not what it should be: malformed, an algorithm we do not
  // allow, no key for it, or a signature that does not verify.
  return new SignInRefused('bad-token');
}

/**
 * Checks an ID token and returns who it says the person is. Signature (RS256 only, against the
 * directory's published keys), audience (our client id), expiry and start time are checked by
 * `jose`. Then: the issuer must be the issuer of the token's own directory, that directory must be
 * bound to a tenant (and, when only one directory is bound, be that one), and the nonce must be the
 * one this sign-in sent. The name and email in the token are never read.
 */
export async function verifyIdToken(
  config: EntraConfig,
  idToken: string,
  nonce: string,
  now: Date = new Date(),
): Promise<Identity> {
  if (typeof idToken !== 'string' || idToken.length === 0 || idToken.length > ID_TOKEN_MAX_LENGTH || idToken.split('.').length !== 3) {
    throw new SignInRefused('bad-token');
  }
  let claims: Record<string, unknown>;
  try {
    const { payload } = await jwtVerify(idToken, keysFor(config), {
      algorithms: ['RS256'],
      audience: config.clientId,
      clockTolerance: CLOCK_TOLERANCE_SECONDS,
      currentDate: now,
      requiredClaims: ['iss', 'exp'],
    });
    claims = payload;
  } catch (error) {
    throw refusalFor(error);
  }

  const { tid, oid, iss } = claims;
  if (typeof tid !== 'string' || !isGuid(tid) || typeof oid !== 'string' || !isGuid(oid)) {
    throw new SignInRefused('bad-claims');
  }
  const directoryId = tid.toLowerCase();
  if (iss !== `${config.authorityHost}/${tid}/v2.0`) throw new SignInRefused('wrong-issuer');
  const [only] = config.bindings;
  if (config.bindings.length === 1 && only && only.directoryId !== directoryId) {
    throw new SignInRefused('wrong-issuer');
  }
  const binding = bindingFor(config, directoryId);
  if (!binding) throw new SignInRefused('unbound-directory');
  if (typeof claims.nonce !== 'string' || !sameText(claims.nonce, nonce)) throw new SignInRefused('nonce');

  return { oid: oid.toLowerCase(), directoryId, roles: claims.roles, binding };
}
