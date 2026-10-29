import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { exportJWK, generateKeyPair, SignJWT, type JWK, type CryptoKey } from 'jose';

// A recording fake of the Microsoft Entra ID (v2.0) OpenID Connect endpoints.
//
// Entra is an external service and this build has no credential for it, so the
// staff sign-in (W09) is built and tested against this fake. It is not a copy of
// Entra: it checks the parts of the protocol the sign-in relies on (the
// authorisation request, PKCE with S256, a one-time code, the client secret and
// the redirect URI at the token endpoint) and signs ID tokens with a key of its
// own, published at its JWKS endpoint. Everything it is sent is recorded, so a
// test can show what crossed the wire and where.
//
// It has no Next, Vitest or MSW import: the unit tests reach it through MSW
// handlers (test/msw/handlers/entra.ts) and the browser tests through a real
// HTTP server (e2e/support/oidc.ts).

export type Endpoint = 'authorize' | 'token' | 'keys';

export type Recorded = {
  endpoint: Endpoint;
  /** The directory (or `organizations`) the path named. */
  directory: string;
  /** Query parameters for authorize, form fields for token, none for keys. */
  params: Record<string, string>;
};

/** What a person signing in is, as the fake knows it. */
export type FakeUser = {
  /** The object id in the directory. */
  oid: string;
  /** Entra app roles. Left out of the token when undefined. */
  roles?: string[];
  /** The directory the person belongs to. Defaults to the one the request named. */
  tid?: string;
};

/** Ways to make the ID token wrong, one at a time, for the refusal tests. */
export type Tamper = {
  iss?: string;
  aud?: string | string[];
  /** Seconds from now. A negative value is in the past. */
  expiresIn?: number;
  /** Seconds from now. A positive value is in the future. */
  notBefore?: number;
  nonce?: string;
  tid?: string;
  oid?: string;
  /** Claims to leave out. */
  omit?: string[];
  /** Sign with a key the JWKS does not publish. */
  signWith?: 'unpublished-key';
  /** Sign with HS256 and the client secret (the algorithm-confusion attempt). */
  algorithm?: 'HS256' | 'none';
  /** Publish a different `kid` than the one the token names. */
  kid?: string;
};

export type FakeEntraOptions = {
  /** Scheme and host, no trailing slash, for example https://login.example.test */
  host: string;
  clientId: string;
  clientSecret: string;
  redirectUri: string;
  /** The directories the fake serves, besides `organizations`. */
  directories: string[];
};

type Issued = {
  user: FakeUser;
  directory: string;
  nonce: string;
  challenge: string;
  redirectUri: string;
  tamper: Tamper;
  used: boolean;
};

export type TokenResult = { status: number; body: Record<string, unknown> };

const KID = 'fake-entra-key-1';
const SAMPLE_NAME = 'Sample Staff Member';
const SAMPLE_ADDRESS = 'sample.staff@example.test';

function s256(verifier: string): string {
  return createHash('sha256').update(verifier).digest('base64url');
}

function same(a: string, b: string): boolean {
  const left = createHash('sha256').update(a).digest();
  const right = createHash('sha256').update(b).digest();
  return timingSafeEqual(left, right);
}

export class FakeEntra {
  readonly requests: Recorded[] = [];
  readonly options: FakeEntraOptions;
  private signing!: CryptoKey;
  private other!: CryptoKey;
  private publicJwk!: JWK;
  private readonly codes = new Map<string, Issued>();

  constructor(options: FakeEntraOptions) {
    this.options = options;
  }

  static async create(options: FakeEntraOptions): Promise<FakeEntra> {
    const fake = new FakeEntra(options);
    const pair = await generateKeyPair('RS256', { extractable: true });
    const unpublished = await generateKeyPair('RS256', { extractable: true });
    fake.signing = pair.privateKey;
    fake.other = unpublished.privateKey;
    fake.publicJwk = { ...(await exportJWK(pair.publicKey)), kid: KID, alg: 'RS256', use: 'sig' };
    return fake;
  }

  /** The address the sign-in sends the browser to for one directory. */
  authorizeUrl(directory: string): string {
    return `${this.options.host}/${directory}/oauth2/v2.0/authorize`;
  }

  tokenUrl(directory: string): string {
    return `${this.options.host}/${directory}/oauth2/v2.0/token`;
  }

  keysUrl(directory: string): string {
    return `${this.options.host}/${directory}/discovery/v2.0/keys`;
  }

  issuerFor(directoryId: string): string {
    return `${this.options.host}/${directoryId}/v2.0`;
  }

  private serves(directory: string): boolean {
    return directory === 'organizations' || this.options.directories.includes(directory);
  }

  recorded(endpoint: Endpoint): Recorded[] {
    return this.requests.filter((r) => r.endpoint === endpoint);
  }

  /**
   * The browser follows the sign-in's redirect to the authorize endpoint and the person signs in.
   * Returns the address the browser is sent back to (the redirect URI with a code and the state),
   * or an error address when the request is not one this fake accepts.
   */
  authorize(address: string, user: FakeUser, tamper: Tamper = {}): { location: string } {
    const url = new URL(address);
    const directory = url.pathname.split('/')[1] ?? '';
    const params = Object.fromEntries(url.searchParams.entries());
    this.requests.push({ endpoint: 'authorize', directory, params });
    const state = params.state ?? '';
    const refuse = (error: string) => {
      const back = new URL(this.options.redirectUri);
      back.searchParams.set('error', error);
      if (state) back.searchParams.set('state', state);
      return { location: back.toString() };
    };

    if (!url.pathname.endsWith('/oauth2/v2.0/authorize') || !this.serves(directory)) return refuse('invalid_request');
    if (params.client_id !== this.options.clientId) return refuse('unauthorized_client');
    if (params.response_type !== 'code') return refuse('unsupported_response_type');
    if (params.redirect_uri !== this.options.redirectUri) return refuse('invalid_request');
    if (!(params.scope ?? '').split(' ').includes('openid')) return refuse('invalid_scope');
    if (!state || !params.nonce) return refuse('invalid_request');
    if (params.code_challenge_method !== 'S256' || !params.code_challenge) return refuse('invalid_request');

    const code = randomBytes(24).toString('base64url');
    this.codes.set(code, {
      user,
      directory,
      nonce: params.nonce,
      challenge: params.code_challenge,
      redirectUri: params.redirect_uri,
      tamper,
      used: false,
    });
    const back = new URL(this.options.redirectUri);
    back.searchParams.set('code', code);
    back.searchParams.set('state', state);
    return { location: back.toString() };
  }

  /** The token endpoint. The sign-in's server calls it with the code and the PKCE verifier. */
  async token(directory: string, form: URLSearchParams, now: Date = new Date()): Promise<TokenResult> {
    const params = Object.fromEntries(form.entries());
    this.requests.push({ endpoint: 'token', directory, params });
    const fail = (error: string, status = 400): TokenResult => ({ status, body: { error } });

    if (!this.serves(directory)) return fail('invalid_request');
    if (params.grant_type !== 'authorization_code') return fail('unsupported_grant_type');
    if (params.client_id !== this.options.clientId) return fail('invalid_client', 401);
    if (!params.client_secret || !same(params.client_secret, this.options.clientSecret)) {
      return fail('invalid_client', 401);
    }
    const issued = this.codes.get(params.code ?? '');
    if (!issued || issued.used) return fail('invalid_grant');
    issued.used = true; // a code works once, also when the rest of the request is wrong
    if (issued.directory !== directory) return fail('invalid_grant');
    if (params.redirect_uri !== issued.redirectUri) return fail('invalid_grant');
    if (!params.code_verifier || !same(s256(params.code_verifier), issued.challenge)) return fail('invalid_grant');

    return {
      status: 200,
      body: {
        token_type: 'Bearer',
        scope: 'openid',
        expires_in: 3600,
        // Not a real token. The sign-in must never read, keep or send it anywhere.
        access_token: 'fake-access-token-never-to-be-used',
        id_token: await this.idToken(issued, now),
      },
    };
  }

  keys(directory: string): TokenResult {
    this.requests.push({ endpoint: 'keys', directory, params: {} });
    if (!this.serves(directory)) return { status: 404, body: { error: 'not_found' } };
    return { status: 200, body: { keys: [this.publicJwk] } };
  }

  private async idToken(issued: Issued, now: Date): Promise<string> {
    const t = issued.tamper;
    const seconds = Math.floor(now.getTime() / 1000);
    const tid = t.tid ?? issued.user.tid ?? issued.directory;
    const claims: Record<string, unknown> = {
      iss: t.iss ?? this.issuerFor(tid),
      aud: t.aud ?? this.options.clientId,
      iat: seconds,
      nbf: seconds + (t.notBefore ?? 0),
      exp: seconds + (t.expiresIn ?? 3600),
      ver: '2.0',
      tid,
      oid: t.oid ?? issued.user.oid,
      sub: 'pairwise-subject-not-the-object-id',
      nonce: t.nonce ?? issued.nonce,
      // Entra puts these in the ID token. The sign-in must drop them.
      name: SAMPLE_NAME,
      preferred_username: SAMPLE_ADDRESS,
    };
    if (issued.user.roles !== undefined) claims.roles = issued.user.roles;
    for (const name of t.omit ?? []) delete claims[name];

    if (t.algorithm === 'none') {
      const encode = (v: unknown) => Buffer.from(JSON.stringify(v)).toString('base64url');
      return `${encode({ alg: 'none', typ: 'JWT' })}.${encode(claims)}.`;
    }
    if (t.algorithm === 'HS256') {
      return new SignJWT(claims)
        .setProtectedHeader({ alg: 'HS256', kid: KID })
        .sign(new TextEncoder().encode(this.options.clientSecret.padEnd(32, '!')));
    }
    return new SignJWT(claims)
      .setProtectedHeader({ alg: 'RS256', kid: t.kid ?? KID, typ: 'JWT' })
      .sign(t.signWith === 'unpublished-key' ? this.other : this.signing);
  }
}
