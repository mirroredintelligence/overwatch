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
  DIRECTORY_PLATFORM,
  DIRECTORY_UNBOUND,
  ENTRA_ENV,
  HOST,
  OID_ADVISOR,
  REDIRECT_URI,
  SINGLE_BINDING,
  TENANT_A,
  TENANT_B,
} from '@/test/oidc/constants';
import type { FakeEntra, FakeUser, Tamper } from '@/test/oidc/fake-entra';
import { idTokenFrom, startFakeEntra } from '@/test/oidc/harness';
import {
  authorizeUrl,
  bindingFor,
  entraAuthorityOrigin,
  exchangeCode,
  loadEntraConfig,
  newTransaction,
  SignInRefused,
  verifyIdToken,
  type EntraConfig,
} from './oidc';

const NOW = new Date();
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
  it('reads the client, the directories bound to tenants and the public address', () => {
    expect(config.clientId).toBe(CLIENT_ID);
    expect(config.authorityHost).toBe(HOST);
    expect(config.publicUrl).toBe('https://capacity.example.test');
    expect(config.bindings).toEqual([
      { directoryId: DIRECTORY_A, tenantId: TENANT_A, platform: false },
      { directoryId: DIRECTORY_B, tenantId: TENANT_B, platform: false },
      { directoryId: DIRECTORY_PLATFORM, tenantId: 'platform-ops', platform: true },
    ]);
  });

  it.each(['ENTRA_CLIENT_ID', 'ENTRA_CLIENT_SECRET', 'DIUCS_PUBLIC_URL', 'DIUCS_ENTRA_BINDINGS'])(
    'refuses to load without %s, naming the variable',
    (name) => {
      expect(() => loadEntraConfig({ ...ENTRA_ENV, [name]: undefined })).toThrow(name);
      expect(() => loadEntraConfig({ ...ENTRA_ENV, [name]: '' })).toThrow(name);
    },
  );

  it('defaults the authority host to Microsoft', () => {
    expect(loadEntraConfig({ ...ENTRA_ENV, ENTRA_AUTHORITY_HOST: undefined }).authorityHost).toBe(
      'https://login.microsoftonline.com',
    );
  });

  it.each([
    ['not JSON', 'not json'],
    ['not a list', '{}'],
    ['an empty list', '[]'],
    ['a directory that is not a GUID', JSON.stringify([{ directoryId: 'common', tenantId: TENANT_A }])],
    ['a tenant id that is not valid', JSON.stringify([{ directoryId: DIRECTORY_A, tenantId: 'Trust A' }])],
    ['a network id as the tenant', JSON.stringify([{ directoryId: DIRECTORY_A, tenantId: 'net-abcdef' }])],
    [
      'one directory bound twice',
      JSON.stringify([
        { directoryId: DIRECTORY_A, tenantId: TENANT_A },
        { directoryId: DIRECTORY_A, tenantId: TENANT_B },
      ]),
    ],
    ['an entry that is not an object', JSON.stringify([7])],
    ['an entry that is null', JSON.stringify([null])],
    ['an entry that is a list', JSON.stringify([[DIRECTORY_A, TENANT_A]])],
    ['a directory that is a number', JSON.stringify([{ directoryId: 7, tenantId: TENANT_A }])],
    ['a key it does not know', JSON.stringify([{ directoryId: DIRECTORY_A, tenantId: TENANT_A, role: 'support' }])],
    ['a platform flag that is not a boolean', JSON.stringify([{ directoryId: DIRECTORY_A, tenantId: TENANT_A, platform: 'yes' }])],
  ])('refuses bindings with %s', (_name, bindings) => {
    expect(() => loadEntraConfig({ ...ENTRA_ENV, DIUCS_ENTRA_BINDINGS: bindings })).toThrow('DIUCS_ENTRA_BINDINGS');
  });

  it('refuses an authority host that is not https in production, and a public address with a path', () => {
    expect(() =>
      loadEntraConfig({ ...ENTRA_ENV, ENTRA_AUTHORITY_HOST: 'http://login.example.test', NODE_ENV: 'production' }),
    ).toThrow('ENTRA_AUTHORITY_HOST');
    expect(() => loadEntraConfig({ ...ENTRA_ENV, DIUCS_PUBLIC_URL: 'https://capacity.example.test/app' })).toThrow(
      'DIUCS_PUBLIC_URL',
    );
    expect(loadEntraConfig({ ...ENTRA_ENV, ENTRA_AUTHORITY_HOST: 'http://127.0.0.1:4011', NODE_ENV: 'development' }).authorityHost).toBe(
      'http://127.0.0.1:4011',
    );
  });

  it('refuses addresses that are not addresses', () => {
    expect(() => loadEntraConfig({ ...ENTRA_ENV, DIUCS_PUBLIC_URL: 'not an address' })).toThrow('DIUCS_PUBLIC_URL');
    expect(() => loadEntraConfig({ ...ENTRA_ENV, ENTRA_AUTHORITY_HOST: 'ftp://login.example.test' })).toThrow('ENTRA_AUTHORITY_HOST');
  });

  it('never puts the client secret in an error', () => {
    try {
      loadEntraConfig({ ...ENTRA_ENV, DIUCS_ENTRA_BINDINGS: 'not json' });
    } catch (error) {
      expect(String(error)).not.toContain(CLIENT_SECRET);
    }
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

describe('bindingFor', () => {
  it('finds the tenant a directory is bound to, and nothing for another directory', () => {
    expect(bindingFor(config, DIRECTORY_A)?.tenantId).toBe(TENANT_A);
    expect(bindingFor(config, DIRECTORY_B)?.tenantId).toBe(TENANT_B);
    expect(bindingFor(config, DIRECTORY_UNBOUND)).toBeUndefined();
    expect(bindingFor(config, DIRECTORY_A.toUpperCase())?.tenantId).toBe(TENANT_A);
    expect(bindingFor(config, '')).toBeUndefined();
  });
});

describe('newTransaction', () => {
  it('makes a new state, nonce and verifier each time, and keeps next', () => {
    const one = newTransaction('/lead');
    const two = newTransaction('/lead');
    expect(one.next).toBe('/lead');
    for (const key of ['state', 'nonce', 'verifier'] as const) {
      expect(one[key]).not.toBe(two[key]);
      expect(one[key]).toMatch(/^[A-Za-z0-9_-]{43}$/);
    }
    expect(new Set([one.state, one.nonce, one.verifier]).size).toBe(3);
  });
});

describe('authorizeUrl', () => {
  it('asks the one bound directory directly when there is only one', () => {
    const single = loadEntraConfig({ ...ENTRA_ENV, DIUCS_ENTRA_BINDINGS: SINGLE_BINDING });
    const url = authorizeUrl(single, newTransaction('/'));
    expect(url.origin + url.pathname).toBe(`${HOST}/${DIRECTORY_A}/oauth2/v2.0/authorize`);
  });

  it('asks the organizations endpoint when several directories are bound', () => {
    const url = authorizeUrl(config, newTransaction('/'));
    expect(url.origin + url.pathname).toBe(`${HOST}/organizations/oauth2/v2.0/authorize`);
  });

  it('is a code request with PKCE S256, a state, a nonce, the fixed redirect address and the openid scope only', () => {
    const transaction = newTransaction('/lead');
    const url = authorizeUrl(config, transaction);
    const q = url.searchParams;
    expect(q.get('client_id')).toBe(CLIENT_ID);
    expect(q.get('response_type')).toBe('code');
    expect(q.get('redirect_uri')).toBe(REDIRECT_URI);
    expect(q.get('scope')).toBe('openid');
    expect(q.get('response_mode')).toBe('query');
    expect(q.get('state')).toBe(transaction.state);
    expect(q.get('nonce')).toBe(transaction.nonce);
    expect(q.get('code_challenge_method')).toBe('S256');
    expect(q.get('code_challenge')).toBe(createHash('sha256').update(transaction.verifier).digest('base64url'));
    expect(q.get('prompt')).toBe('select_account');
  });

  it('carries no secret, no verifier, no tenant and no next', () => {
    const transaction = newTransaction('/lead');
    const text = authorizeUrl(config, transaction).toString();
    expect(text).not.toContain(CLIENT_SECRET);
    expect(text).not.toContain(transaction.verifier);
    expect(text).not.toContain('lead');
    expect(text).not.toMatch(/tenant|login_hint|domain_hint/);
  });

  it('is accepted by the fake provider', () => {
    const { location } = fake.authorize(authorizeUrl(config, newTransaction('/')).toString(), USER);
    expect(new URL(location).searchParams.get('code')).not.toBeNull();
  });
});

describe('exchangeCode', () => {
  function issue(transaction = newTransaction('/')) {
    const { location } = fake.authorize(authorizeUrl(config, transaction).toString(), USER);
    return { transaction, code: new URL(location).searchParams.get('code') ?? '' };
  }

  it('redeems the code with the verifier and the client secret, and returns the ID token only', async () => {
    const { transaction, code } = issue();
    const idToken = await exchangeCode(config, code, transaction);
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
    await exchangeCode(config, code, transaction);
    const withSecret = fake.requests.filter((r) => JSON.stringify(r.params).includes(CLIENT_SECRET));
    expect(withSecret.map((r) => r.endpoint)).toEqual(['token']);
  });

  it('is refused when the provider refuses the code', async () => {
    const { transaction } = issue();
    expect(await reasonOf(exchangeCode(config, 'not-a-code', transaction))).toBe('token-exchange');
  });

  it('is refused when the verifier is not the one the challenge was made from', async () => {
    const { transaction, code } = issue();
    expect(await reasonOf(exchangeCode(config, code, { ...transaction, verifier: 'x'.repeat(43) }))).toBe('token-exchange');
  });

  it.each([
    ['no id_token', { token_type: 'Bearer', access_token: 'x' }],
    ['an id_token that is not text', { id_token: 7 }],
    ['an empty id_token', { id_token: '' }],
    ['a body that is not an object', 7],
    ['a null body', null],
  ])('is refused when the answer has %s', async (_name, body) => {
    server.use(http.post(`${HOST}/:directory/oauth2/v2.0/token`, () => HttpResponse.json(body)));
    expect(await reasonOf(exchangeCode(config, 'code', newTransaction('/')))).toBe('token-exchange');
  });

  it.each([400, 401, 500])('is refused on a %s answer, whatever the body holds', async (status) => {
    server.use(http.post(`${HOST}/:directory/oauth2/v2.0/token`, () => HttpResponse.json({ id_token: 'a.b.c' }, { status })));
    expect(await reasonOf(exchangeCode(config, 'code', newTransaction('/')))).toBe('token-exchange');
  });

  it('is refused when the provider cannot be reached or answers with something that is not JSON', async () => {
    server.use(http.post(`${HOST}/:directory/oauth2/v2.0/token`, () => HttpResponse.error()));
    expect(await reasonOf(exchangeCode(config, 'code', newTransaction('/')))).toBe('token-exchange');
    server.use(http.post(`${HOST}/:directory/oauth2/v2.0/token`, () => new HttpResponse('<html>', { status: 200 })));
    expect(await reasonOf(exchangeCode(config, 'code', newTransaction('/')))).toBe('token-exchange');
  });

  it('puts neither the code nor the secret in the refusal', async () => {
    try {
      await exchangeCode(config, 'code-value-12345', newTransaction('/'));
    } catch (error) {
      expect(String(error)).not.toContain('code-value-12345');
      expect(String(error)).not.toContain(CLIENT_SECRET);
    }
  });
});

describe('verifyIdToken', () => {
  it('accepts a good token and returns the object id, the directory and the roles, and nothing else', async () => {
    const identity = await verify();
    expect(identity).toEqual({
      oid: OID_ADVISOR,
      directoryId: DIRECTORY_A,
      roles: ['DIUCS.Advisor'],
      binding: { directoryId: DIRECTORY_A, tenantId: TENANT_A, platform: false },
    });
    expect(JSON.stringify(identity)).not.toMatch(/Sample|example\.test/);
  });

  it('takes the keys from the directory it asked when one directory is bound, and from organizations when several are', async () => {
    const single = loadEntraConfig({ ...ENTRA_ENV, DIUCS_ENTRA_BINDINGS: SINGLE_BINDING });
    const token = await idTokenFrom(fake, USER, { nonce: 'n', directory: DIRECTORY_A });
    await verifyIdToken(single, token, 'n', NOW);
    expect(fake.recorded('keys').at(-1)?.directory).toBe(DIRECTORY_A);

    const many = loadEntraConfig({ ...ENTRA_ENV });
    const other = await idTokenFrom(fake, { ...USER, tid: DIRECTORY_B }, { nonce: 'n', directory: 'organizations' });
    await verifyIdToken(many, other, 'n', NOW);
    expect(fake.recorded('keys').at(-1)?.directory).toBe('organizations');
  });

  it('binds a person from another bound directory to that directory’s tenant', async () => {
    const identity = await verify({}, { ...USER, tid: DIRECTORY_B }, 'nonce-1', 'organizations');
    expect(identity.binding.tenantId).toBe(TENANT_B);
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

  it('refuses a token from a directory that is signed correctly but not bound to a tenant', async () => {
    const reason = await reasonOf(verify({}, { ...USER, tid: DIRECTORY_UNBOUND }, 'nonce-1', 'organizations'));
    expect(reason).toBe('unbound-directory');
  });

  it('refuses, for a single bound directory, a token from any other directory even when it is signed correctly', async () => {
    const single = loadEntraConfig({ ...ENTRA_ENV, DIUCS_ENTRA_BINDINGS: SINGLE_BINDING });
    const token = await idTokenFrom(fake, { ...USER, tid: DIRECTORY_B }, { nonce: 'n', directory: 'organizations' });
    expect(await reasonOf(verifyIdToken(single, token, 'n', NOW))).toBe('wrong-issuer');
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
