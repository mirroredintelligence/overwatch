// @vitest-environment node
import { createHash } from 'node:crypto';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import {
  CLIENT_ID,
  CLIENT_SECRET,
  DIRECTORY_A,
  DIRECTORY_B,
  DIRECTORY_UNBOUND,
  ENTRA_ENV,
  HOST,
  OID_ADVISOR,
  PUBLIC_URL,
  PUBLIC_URL_B,
  REDIRECT_URI,
  REDIRECT_URI_B,
} from '@/test/oidc/constants';
import type { FakeEntra, FakeUser, Tamper } from '@/test/oidc/fake-entra';
import { idTokenFrom, startFakeEntra } from '@/test/oidc/harness';
import {
  authorizeUrl,
  callbackAddress,
  entraAuthorityOrigin,
  exchangeCode,
  loadEntraConfig,
  newTransaction,
  SignInRefused,
  verifyIdToken,
  type EntraConfig,
} from './oidc';

const NOW = new Date();
const ADDRESS = REDIRECT_URI;
const USER: FakeUser = { oid: OID_ADVISOR, roles: ['DIUCS.Advisor'] };

let fake: FakeEntra;
let config: EntraConfig;

beforeEach(async () => {
  fake = await startFakeEntra();
  config = loadEntraConfig({ ...ENTRA_ENV });
});
afterEach(() => vi.unstubAllEnvs());

async function reasonOf(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof SignInRefused) return error.reason;
    throw error;
  }
  return 'accepted';
}

async function verify(tamper: Tamper = {}, user: FakeUser = USER, nonce = 'nonce-1', directory = DIRECTORY_A) {
  const token = await idTokenFrom(fake, user, { nonce, tamper, directory });
  return verifyIdToken(config, token, nonce, NOW);
}

describe('loadEntraConfig', () => {
  it('reads the client and the provider and nothing about tenants, directories or the site’s own address', () => {
    expect(config).toEqual({ clientId: CLIENT_ID, clientSecret: CLIENT_SECRET, authorityHost: HOST });
  });

  it.each(['ENTRA_CLIENT_ID', 'ENTRA_CLIENT_SECRET'])('refuses to load without %s, naming the variable', (name) => {
    expect(() => loadEntraConfig({ ...ENTRA_ENV, [name]: undefined })).toThrow(name);
    expect(() => loadEntraConfig({ ...ENTRA_ENV, [name]: '' })).toThrow(name);
  });

  it('loads without DIUCS_ENTRA_BINDINGS, DIUCS_PUBLIC_URL or a signing secret, and ignores them when they are set', () => {
    const loaded = loadEntraConfig({ ...ENTRA_ENV, DIUCS_ENTRA_BINDINGS: 'not json', DIUCS_PUBLIC_URL: 'nonsense', BACKEND_JWT_SECRET: 'x' });
    expect(Object.keys(loaded).sort()).toEqual(['authorityHost', 'clientId', 'clientSecret']);
  });

  it('defaults the authority host to Microsoft', () => {
    expect(loadEntraConfig({ ...ENTRA_ENV, ENTRA_AUTHORITY_HOST: undefined }).authorityHost).toBe(
      'https://login.microsoftonline.com',
    );
  });

  it('refuses an authority host that is not https in production, and allows http in development', () => {
    expect(() =>
      loadEntraConfig({ ...ENTRA_ENV, ENTRA_AUTHORITY_HOST: 'http://login.example.test', NODE_ENV: 'production' }),
    ).toThrow('ENTRA_AUTHORITY_HOST');
    expect(loadEntraConfig({ ...ENTRA_ENV, ENTRA_AUTHORITY_HOST: 'http://127.0.0.1:4011', NODE_ENV: 'development' }).authorityHost).toBe(
      'http://127.0.0.1:4011',
    );
  });

  it('refuses addresses that are not addresses, or carry a path', () => {
    expect(() => loadEntraConfig({ ...ENTRA_ENV, ENTRA_AUTHORITY_HOST: 'ftp://login.example.test' })).toThrow('ENTRA_AUTHORITY_HOST');
    expect(() => loadEntraConfig({ ...ENTRA_ENV, ENTRA_AUTHORITY_HOST: 'https://login.example.test/path' })).toThrow('ENTRA_AUTHORITY_HOST');
  });

  it('never puts the client secret in an error', () => {
    try {
      loadEntraConfig({ ...ENTRA_ENV, ENTRA_AUTHORITY_HOST: 'not an address' });
    } catch (error) {
      expect(String(error)).not.toContain(CLIENT_SECRET);
    }
  });
});

describe('callbackAddress', () => {
  const at = (url: string, headers: Record<string, string> = {}) => new Request(url, { headers });

  it('is the callback on the host the request was addressed to: one address per tenant host', () => {
    expect(callbackAddress(at(`${PUBLIC_URL}/x`), { NODE_ENV: 'production' })).toBe(REDIRECT_URI);
    expect(callbackAddress(at(`${PUBLIC_URL_B}/x`), { NODE_ENV: 'production' })).toBe(REDIRECT_URI_B);
  });

  it('is https in production whatever scheme the request URL shows (a proxy ends TLS)', () => {
    expect(callbackAddress(at('http://tenant-a.example.test/x'), { NODE_ENV: 'production' })).toBe(REDIRECT_URI);
  });

  it('keeps the scheme and the port of the request outside production', () => {
    expect(callbackAddress(at('http://localhost:20000/x'), { NODE_ENV: 'development' })).toBe(
      'http://localhost:20000/api/bff/auth/entra/callback',
    );
  });

  it('reads the Host header and no forwarded or tenant header', () => {
    const request = at(`${PUBLIC_URL}/x`, { 'X-Forwarded-Host': 'tenant-b.example.test', Forwarded: 'host=tenant-b.example.test' });
    expect(callbackAddress(request, { NODE_ENV: 'production' })).toBe(REDIRECT_URI);
  });

  it('is null for a host that is not a host name', () => {
    expect(callbackAddress(at(`${PUBLIC_URL}/x`, { Host: 'tenant-a.example.test/evil' }), { NODE_ENV: 'production' })).toBeNull();
    expect(callbackAddress(at(`${PUBLIC_URL}/x`, { Host: 'user@tenant-a.example.test' }), { NODE_ENV: 'production' })).toBeNull();
  });
});

describe('entraAuthorityOrigin', () => {
  it('is the Microsoft sign-in host when nothing is set', () => {
    expect(entraAuthorityOrigin({})).toBe('https://login.microsoftonline.com');
  });

  it('is the configured host, as an origin', () => {
    expect(entraAuthorityOrigin({ ENTRA_AUTHORITY_HOST: 'https://login.example.test' })).toBe('https://login.example.test');
    expect(entraAuthorityOrigin({ ENTRA_AUTHORITY_HOST: 'http://127.0.0.1:4011' })).toBe('http://127.0.0.1:4011');
  });

  it.each([
    { ENTRA_AUTHORITY_HOST: 'not an address' },
    { ENTRA_AUTHORITY_HOST: 'https://login.example.test/some/path' },
    { ENTRA_AUTHORITY_HOST: 'https://user:pw@login.example.test' },
    { ENTRA_AUTHORITY_HOST: 'ftp://login.example.test' },
    { ENTRA_AUTHORITY_HOST: 'http://login.example.test', NODE_ENV: 'production' },
  ])('is null, never a throw, for a setting the sign-in would refuse: %j', (env) => {
    expect(entraAuthorityOrigin(env)).toBeNull();
  });
});

describe('newTransaction', () => {
  it('makes a new state, nonce and verifier each time, and keeps next and the host it began on', () => {
    const one = newTransaction('/lead', 'tenant-a.example.test');
    const two = newTransaction('/lead', 'tenant-a.example.test');
    expect(one.next).toBe('/lead');
    expect(one.host).toBe('tenant-a.example.test');
    for (const key of ['state', 'nonce', 'verifier'] as const) {
      expect(one[key]).not.toBe(two[key]);
      expect(one[key]).toMatch(/^[A-Za-z0-9_-]{43}$/);
    }
    expect(new Set([one.state, one.nonce, one.verifier]).size).toBe(3);
  });
});

describe('authorizeUrl', () => {
  it('asks the organizations endpoint: the front end knows no directory', () => {
    const url = authorizeUrl(config, newTransaction('/', 'tenant-a.example.test'), ADDRESS);
    expect(url.origin + url.pathname).toBe(`${HOST}/organizations/oauth2/v2.0/authorize`);
  });

  it('is a code request with PKCE S256, a state, a nonce, the fixed redirect address and the openid scope only', () => {
    const transaction = newTransaction('/lead', 'tenant-a.example.test');
    const url = authorizeUrl(config, transaction, ADDRESS);
    const q = url.searchParams;
    expect(q.get('client_id')).toBe(CLIENT_ID);
    expect(q.get('response_type')).toBe('code');
    expect(q.get('redirect_uri')).toBe(ADDRESS);
    expect(q.get('scope')).toBe('openid');
    expect(q.get('response_mode')).toBe('query');
    expect(q.get('state')).toBe(transaction.state);
    expect(q.get('nonce')).toBe(transaction.nonce);
    expect(q.get('code_challenge_method')).toBe('S256');
    expect(q.get('code_challenge')).toBe(createHash('sha256').update(transaction.verifier).digest('base64url'));
    expect(q.get('prompt')).toBe('select_account');
  });

  it('carries no secret, no verifier, no tenant and no next', () => {
    const transaction = newTransaction('/lead', 'tenant-a.example.test');
    const text = authorizeUrl(config, transaction, ADDRESS).toString();
    expect(text).not.toContain(CLIENT_SECRET);
    expect(text).not.toContain(transaction.verifier);
    expect(text).not.toContain('lead');
    // No parameter names a tenant, a directory hint or a login hint (the redirect address is a value).
    expect([...authorizeUrl(config, transaction, ADDRESS).searchParams.keys()].join(' ')).not.toMatch(/tenant|login_hint|domain_hint|directory/);
  });

  it('sends the address it is given, so each tenant host has its own', () => {
    const b = authorizeUrl(config, newTransaction('/', 'tenant-b.example.test'), REDIRECT_URI_B);
    expect(b.searchParams.get('redirect_uri')).toBe(REDIRECT_URI_B);
  });

  it('is accepted by the fake provider', () => {
    const { location } = fake.authorize(authorizeUrl(config, newTransaction('/', 'tenant-a.example.test'), ADDRESS).toString(), USER);
    expect(new URL(location).searchParams.get('code')).not.toBeNull();
  });
});

describe('exchangeCode', () => {
  function issue(transaction = newTransaction('/', 'tenant-a.example.test')) {
    const { location } = fake.authorize(authorizeUrl(config, transaction, ADDRESS).toString(), USER);
    return { transaction, code: new URL(location).searchParams.get('code') ?? '' };
  }

  it('redeems the code with the verifier and the client secret, and returns the ID token only', async () => {
    const { transaction, code } = issue();
    const idToken = await exchangeCode(config, code, transaction, ADDRESS);
    expect(idToken.split('.')).toHaveLength(3);
    const sent = fake.recorded('token').at(-1);
    expect(sent?.params).toMatchObject({
      grant_type: 'authorization_code',
      code,
      redirect_uri: REDIRECT_URI,
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET,
      code_verifier: transaction.verifier,
    });
    expect(sent?.directory).toBe('organizations');
  });

  it('sends the client secret to the token endpoint and to nothing else', async () => {
    const { transaction, code } = issue();
    await exchangeCode(config, code, transaction, ADDRESS);
    const withSecret = fake.requests.filter((r) => JSON.stringify(r.params).includes(CLIENT_SECRET));
    expect(withSecret.map((r) => r.endpoint)).toEqual(['token']);
  });

  it('is refused when the provider refuses the code', async () => {
    const { transaction } = issue();
    expect(await reasonOf(exchangeCode(config, 'not-a-code', transaction, ADDRESS))).toBe('token-exchange');
  });

  it('is refused when the verifier is not the one the challenge was made from', async () => {
    const { transaction, code } = issue();
    expect(await reasonOf(exchangeCode(config, code, { ...transaction, verifier: 'x'.repeat(43) }, ADDRESS))).toBe('token-exchange');
  });

  it.each([
    ['no id_token', { token_type: 'Bearer', access_token: 'x' }],
    ['an id_token that is not text', { id_token: 7 }],
    ['an empty id_token', { id_token: '' }],
    ['a body that is not an object', 7],
    ['a null body', null],
  ])('is refused when the answer has %s', async (_name, body) => {
    server.use(http.post(`${HOST}/:directory/oauth2/v2.0/token`, () => HttpResponse.json(body)));
    expect(await reasonOf(exchangeCode(config, 'code', newTransaction('/', 'tenant-a.example.test'), ADDRESS))).toBe('token-exchange');
  });

  it.each([400, 401, 500])('is refused on a %s answer, whatever the body holds', async (status) => {
    server.use(http.post(`${HOST}/:directory/oauth2/v2.0/token`, () => HttpResponse.json({ id_token: 'a.b.c' }, { status })));
    expect(await reasonOf(exchangeCode(config, 'code', newTransaction('/', 'tenant-a.example.test'), ADDRESS))).toBe('token-exchange');
  });

  it('is refused when the provider cannot be reached or answers with something that is not JSON', async () => {
    server.use(http.post(`${HOST}/:directory/oauth2/v2.0/token`, () => HttpResponse.error()));
    expect(await reasonOf(exchangeCode(config, 'code', newTransaction('/', 'tenant-a.example.test'), ADDRESS))).toBe('token-exchange');
    server.use(http.post(`${HOST}/:directory/oauth2/v2.0/token`, () => new HttpResponse('<html>', { status: 200 })));
    expect(await reasonOf(exchangeCode(config, 'code', newTransaction('/', 'tenant-a.example.test'), ADDRESS))).toBe('token-exchange');
  });

  it('puts neither the code nor the secret in the refusal', async () => {
    try {
      await exchangeCode(config, 'code-value-12345', newTransaction('/', 'tenant-a.example.test'), ADDRESS);
    } catch (error) {
      expect(String(error)).not.toContain('code-value-12345');
      expect(String(error)).not.toContain(CLIENT_SECRET);
    }
  });
});

describe('verifyIdToken', () => {
  it('accepts a good token and returns the object id and the directory, and nothing else: no role, no tenant', async () => {
    const identity = await verify();
    expect(identity).toEqual({ oid: OID_ADVISOR, directoryId: DIRECTORY_A });
    expect(JSON.stringify(identity)).not.toMatch(/Sample|example\.test|DIUCS|trust-/);
  });

  it('takes the keys from organizations, and names the directory a person came from without judging it', async () => {
    const other = await idTokenFrom(fake, { ...USER, tid: DIRECTORY_B }, { nonce: 'n', directory: 'organizations' });
    const identity = await verifyIdToken(config, other, 'n', NOW);
    expect(fake.recorded('keys').at(-1)?.directory).toBe('organizations');
    expect(identity.directoryId).toBe(DIRECTORY_B);
  });

  it.each([
    ['a signature from a key the directory does not publish', { signWith: 'unpublished-key' as const }, 'bad-token'],
    ['an unknown key id', { kid: 'some-other-kid' }, 'bad-token'],
    ['HS256 signed with the client secret', { algorithm: 'HS256' as const }, 'bad-token'],
    ['no signature (alg none)', { algorithm: 'none' as const }, 'bad-token'],
    ['RS384, an algorithm other than RS256', { algorithm: 'RS384' as const }, 'bad-token'],
    ['an expiry in the past', { expiresIn: -120 }, 'expired'],
    ['a start in the future', { notBefore: 600 }, 'not-yet-valid'],
    ['another audience', { aud: 'some-other-client' }, 'wrong-audience'],
    ['a list of audiences that leaves ours out', { aud: ['a', 'b'] }, 'wrong-audience'],
    ['another issuer host', { iss: `https://login.other.test/${DIRECTORY_A}/v2.0` }, 'wrong-issuer'],
    ['the issuer of another directory', { iss: `${HOST}/${DIRECTORY_B}/v2.0` }, 'wrong-issuer'],
    ['an issuer with a path added', { iss: `${HOST}/${DIRECTORY_A}/v2.0/extra` }, 'wrong-issuer'],
    ['a directory claim that does not match the issuer', { tid: DIRECTORY_B, iss: `${HOST}/${DIRECTORY_A}/v2.0` }, 'wrong-issuer'],
    ['another nonce', { nonce: 'a-different-nonce' }, 'nonce'],
    ['no nonce', { omit: ['nonce'] }, 'nonce'],
    ['no expiry', { omit: ['exp'] }, 'bad-claims'],
    ['no issuer', { omit: ['iss'] }, 'bad-claims'],
    ['no audience', { omit: ['aud'] }, 'wrong-audience'],
    ['no object id', { omit: ['oid'] }, 'bad-claims'],
    ['an object id that is not a GUID', { oid: 'sample.staff@example.test' }, 'bad-claims'],
    ['no directory claim', { omit: ['tid'] }, 'bad-claims'],
  ] as [string, Tamper, string][])('refuses a token with %s', async (_name, tamper, reason) => {
    expect(await reasonOf(verify(tamper))).toBe(reason);
  });

  it('does not judge the directory: whether a tenant has bound it is the back end’s answer, never this code’s', async () => {
    const identity = await verify({}, { ...USER, tid: DIRECTORY_UNBOUND }, 'nonce-1', 'organizations');
    expect(identity.directoryId).toBe(DIRECTORY_UNBOUND);
  });

  it('refuses a token whose roles were changed after it was signed', async () => {
    const token = await idTokenFrom(fake, USER, { nonce: 'nonce-1' });
    const [head, body, signature] = token.split('.');
    const claims = JSON.parse(Buffer.from(body!, 'base64url').toString());
    claims.roles = ['DIUCS.Lead'];
    const forged = `${head}.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.${signature}`;
    expect(await reasonOf(verifyIdToken(config, forged, 'nonce-1', NOW))).toBe('bad-token');
  });

  it.each(['', 'not-a-token', 'a.b', 'a.b.c', 'a.b.c.d', '.'.repeat(2), 'x'.repeat(20_000)])(
    'refuses %j as a token',
    async (token) => {
      expect(await reasonOf(verifyIdToken(config, token, 'n', NOW))).toBe('bad-token');
    },
  );

  it('refuses when the keys cannot be fetched', async () => {
    server.use(http.get(`${HOST}/:directory/discovery/v2.0/keys`, () => new HttpResponse(null, { status: 500 })));
    expect(await reasonOf(verify())).toBe('keys-unavailable');
  });

  it('accepts a little clock difference and no more', async () => {
    expect(await reasonOf(verify({ expiresIn: -30 }))).toBe('accepted');
    expect(await reasonOf(verify({ notBefore: 30 }))).toBe('accepted');
  });

  it('puts neither the token nor a claim in the refusal', async () => {
    const token = await idTokenFrom(fake, USER, { nonce: 'right' });
    try {
      await verifyIdToken(config, token, 'wrong', NOW);
    } catch (error) {
      expect(String(error)).not.toContain(token);
      expect(String(error)).not.toContain(OID_ADVISOR);
      expect(String(error)).not.toContain('DIUCS.Advisor');
    }
  });
});
