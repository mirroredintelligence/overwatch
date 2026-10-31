import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { createRemoteJWKSet, errors, jwtVerify } from 'jose';
import { getSecret } from '@/lib/secrets';

// OpenID Connect against Microsoft Entra ID: the authorisation code flow with PKCE (S256),
// done here with `jose` and `fetch` and not with Auth.js (DEC-210). Nothing in this file logs,
// and every refusal is one of a fixed list of reasons that holds no token, code or claim.

export type EntraConfig = {
  clientId: string;
  clientSecret: string;
  /** Scheme and host of the Entra authority, no path. */
  authorityHost: string;
  /** This site's own address, from configuration, never from a request. */
  publicUrl: string;
  /**
   * The one directory a single-tenant app registration serves, or null for a multi-tenant one
   * (the shared `organizations` endpoint). Which tenant a directory belongs to is not decided here:
   * the back end decides it from the host and its own records (TEN-043, DEC-523).
   */
  directoryId: string | null;
  /** The path this app's callback is served on. Omitted for the staff sign-in's own. */
  callbackPath?: string;
};

export type Transaction = { state: string; nonce: string; verifier: string; next: string };

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
  // The exchange with the back end (TEN-043): it could not be had, or its answer was not one.
  'exchange-failed',
  'exchange-answer',
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

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isGuid = (value: string) => GUID.test(value);
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

function directoryFrom(env: Env, name: string): string | null {
  const value = env[name];
  if (!value) return null;
  if (!isGuid(value)) throw new Error(`${name} must be a directory id (a GUID)`);
  return value.toLowerCase();
}

function directory(env: Env): string | null {
  return directoryFrom(env, 'ENTRA_DIRECTORY_ID');
}

// The client secrets come from the secret module (Key Vault on the pilot, DEC-1304), never from `env`: the
// settings given here are the non-secret ones (ids, directory, addresses).
const STAFF_SECRET = 'entra-staff-client-secret';
const OPERATOR_SECRET = 'entra-operator-client-secret';

/** Reads the settings at call time, so a missing value fails the request that needs it. */
export async function loadEntraConfig(env: Env = process.env): Promise<EntraConfig> {
  // The settings are checked first, so a bad one never costs a vault call; the secret is read last.
  const clientId = setting(env, 'ENTRA_CLIENT_ID');
  const authorityHost = origin(env, 'ENTRA_AUTHORITY_HOST', env.ENTRA_AUTHORITY_HOST || DEFAULT_AUTHORITY_HOST);
  const publicUrl = origin(env, 'DIUCS_PUBLIC_URL', setting(env, 'DIUCS_PUBLIC_URL'));
  const directoryId = directory(env);
  return { clientId, clientSecret: await getSecret(STAFF_SECRET), authorityHost, publicUrl, directoryId };
}

export const OPERATOR_CALLBACK_PATH = '/api/bff/platform/auth/callback';

/**
 * The operator console's app registration (TEN-083): another client, for the operator's directory ONLY (it
 * must be set: there is no shared endpoint for the platform's own people), served on the console's own
 * address. It shares nothing with the staff sign-in's settings but the identity provider's address, and
 * falls back to none of them: a missing value fails the request that needs it.
 */
export async function loadOperatorEntraConfig(env: Env = process.env): Promise<EntraConfig> {
  const directoryId = directoryFrom(env, 'OPERATOR_ENTRA_DIRECTORY_ID');
  if (directoryId === null) throw new Error('OPERATOR_ENTRA_DIRECTORY_ID is not set');
  const clientId = setting(env, 'OPERATOR_ENTRA_CLIENT_ID');
  const authorityHost = origin(env, 'ENTRA_AUTHORITY_HOST', env.ENTRA_AUTHORITY_HOST || DEFAULT_AUTHORITY_HOST);
  const publicUrl = origin(env, 'DIUCS_OPERATOR_PUBLIC_URL', setting(env, 'DIUCS_OPERATOR_PUBLIC_URL'));
  return { clientId, clientSecret: await getSecret(OPERATOR_SECRET), authorityHost, publicUrl, directoryId, callbackPath: OPERATOR_CALLBACK_PATH };
}

/**
 * The origin the browser is sent to for sign-in, for the sign-in page's content security policy.
 * Null (never a throw) for a setting the sign-in itself would refuse, so the page still renders
 * and the policy then allows no extra target.
 */
export function entraAuthorityOrigin(env: Env = process.env): string | null {
  try {
    return origin(env, 'ENTRA_AUTHORITY_HOST', env.ENTRA_AUTHORITY_HOST || DEFAULT_AUTHORITY_HOST);
  } catch {
    return null;
  }
}

// A single-tenant app registration asks its own directory; a multi-tenant one asks the shared
// `organizations` endpoint, and the token's own directory is then whatever the person signed in to.
function authority(config: EntraConfig): string {
  return config.directoryId ?? SHARED_AUTHORITY;
}

function redirectUri(config: EntraConfig): string {
  return `${config.publicUrl}${config.callbackPath ?? CALLBACK_PATH}`;
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
 * Checks an ID token. Signature (RS256 only, against the directory's published keys), audience (our
 * client id), expiry and start time are checked by `jose`. Then: the issuer must be the issuer of the
 * token's own directory, that directory must be the configured one when there is one, and the nonce
 * must be the one this sign-in sent, which only this side knows. The name and email in the token are
 * never read, and nothing is returned: who the person is and what they may do is the back end's to say
 * (`exchangeStaffToken`), from the host's tenant and its own records.
 */
export async function verifyIdToken(
  config: EntraConfig,
  idToken: string,
  nonce: string,
  now: Date = new Date(),
): Promise<void> {
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
  if (iss !== `${config.authorityHost}/${tid}/v2.0`) throw new SignInRefused('wrong-issuer');
  if (config.directoryId !== null && config.directoryId !== tid.toLowerCase()) throw new SignInRefused('wrong-issuer');
  if (typeof claims.nonce !== 'string' || !sameText(claims.nonce, nonce)) throw new SignInRefused('nonce');
}
