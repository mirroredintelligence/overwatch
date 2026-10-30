import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { createRemoteJWKSet, errors, jwtVerify } from 'jose';
import { requestHost } from './host';
import { isGuid } from './ids';

// OpenID Connect against Microsoft Entra ID: the authorisation code flow with PKCE (S256),
// done here with `jose` and `fetch` and not with Auth.js (DEC-210). Nothing in this file logs,
// and every refusal is one of a fixed list of reasons that holds no token, code or claim.
//
// This code proves who the person is and nothing about which organisation or role: it knows no
// tenant, no directory binding and no role (TEN-044). The identity token goes on to the back end,
// which takes the tenant from the host, checks the directory against the tenant's verified binding
// and gives the role the tenant's own mapping says (lib/auth/exchange.ts, TEN-043).

export type EntraConfig = {
  clientId: string;
  clientSecret: string;
  /** Scheme and host of the Entra authority, no path. */
  authorityHost: string;
};

/**
 * `host` is the host the sign-in began on: the transaction is for that host only, so a sign-in
 * begun on one tenant's host cannot be finished on another's.
 */
export type Transaction = { state: string; nonce: string; verifier: string; next: string; host: string };

export type Identity = {
  oid: string;
  directoryId: string;
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

/** Reads the settings at call time, so a missing value fails the request that needs it. */
export function loadEntraConfig(env: Env = process.env): EntraConfig {
  return {
    clientId: setting(env, 'ENTRA_CLIENT_ID'),
    clientSecret: setting(env, 'ENTRA_CLIENT_SECRET'),
    authorityHost: origin(env, 'ENTRA_AUTHORITY_HOST', env.ENTRA_AUTHORITY_HOST || DEFAULT_AUTHORITY_HOST),
  };
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

// One app registration serves every tenant, so the shared `organizations` endpoint is always asked and
// the person's own directory is named by the token.
const AUTHORITY = 'organizations';

/**
 * The address Entra sends the browser back to: the callback on the host the request was addressed to,
 * because each tenant has its own host (DEC-134 item 3) and its own registered redirect address. The
 * host is the Host header only. In production the scheme is https whatever the request URL shows (a
 * proxy ends TLS); elsewhere it is the request's own. Null when the host is not a host name.
 */
export function callbackAddress(request: Request, env: Env = process.env): string | null {
  const host = requestHost(request);
  if (host === null) return null;
  let scheme = 'https:';
  if (env.NODE_ENV !== 'production') {
    try {
      scheme = new URL(request.url).protocol;
    } catch {
      return null;
    }
    if (scheme !== 'https:' && scheme !== 'http:') return null;
  }
  return `${scheme}//${host}${CALLBACK_PATH}`;
}

function random(): string {
  return randomBytes(32).toString('base64url');
}

export function newTransaction(next: string, host: string): Transaction {
  return { state: random(), nonce: random(), verifier: random(), next, host };
}

export function authorizeUrl(config: EntraConfig, transaction: Transaction, redirectUri: string): URL {
  const url = new URL(`${config.authorityHost}/${AUTHORITY}/oauth2/v2.0/authorize`);
  const query = url.searchParams;
  query.set('client_id', config.clientId);
  query.set('response_type', 'code');
  query.set('redirect_uri', redirectUri);
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
export async function exchangeCode(
  config: EntraConfig,
  code: string,
  transaction: Transaction,
  redirectUri: string,
): Promise<string> {
  const refused = new SignInRefused('token-exchange');
  let body: unknown;
  try {
    const response = await fetch(`${config.authorityHost}/${AUTHORITY}/oauth2/v2.0/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code,
        redirect_uri: redirectUri,
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
  const address = `${config.authorityHost}/${AUTHORITY}/discovery/v2.0/keys`;
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
 * `jose`. Then: the issuer must be the issuer of the token's own directory, and the nonce must be
 * the one this sign-in sent. Whether a tenant has bound the directory is not asked here: that is the
 * back end's answer. The name, email and roles in the token are never read.
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
  if (typeof claims.nonce !== 'string' || !sameText(claims.nonce, nonce)) throw new SignInRefused('nonce');

  return { oid: oid.toLowerCase(), directoryId };
}
