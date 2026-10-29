// @vitest-environment node
import { createHash } from 'node:crypto';
import { decodeJwt, decodeProtectedHeader } from 'jose';
import { beforeAll, describe, expect, it } from 'vitest';
import { CLIENT_ID, CLIENT_SECRET, DIRECTORY_A, DIRECTORY_B, HOST, OID_ADVISOR, REDIRECT_URI } from './constants';
import { FakeEntra } from './fake-entra';

// The fake is test equipment, so it is tested too: a fake that accepts what the
// real service refuses would let a broken sign-in pass.

let fake: FakeEntra;
beforeAll(async () => {
  fake = await FakeEntra.create({
    host: HOST,
    clientId: CLIENT_ID,
    clientSecret: CLIENT_SECRET,
    redirectUri: REDIRECT_URI,
    directories: [DIRECTORY_A, DIRECTORY_B],
  });
});

const VERIFIER = 'v'.repeat(43);
const CHALLENGE = createHash('sha256').update(VERIFIER).digest('base64url');

function request(overrides: Record<string, string> = {}): string {
  const url = new URL(fake.authorizeUrl(DIRECTORY_A));
  const params: Record<string, string> = {
    client_id: CLIENT_ID,
    response_type: 'code',
    redirect_uri: REDIRECT_URI,
    scope: 'openid',
    state: 'state-1',
    nonce: 'nonce-1',
    code_challenge: CHALLENGE,
    code_challenge_method: 'S256',
    ...overrides,
  };
  for (const [k, v] of Object.entries(params)) if (v !== '') url.searchParams.set(k, v);
  return url.toString();
}

function codeOf(location: string): string {
  return new URL(location).searchParams.get('code') ?? '';
}

function form(code: string, overrides: Record<string, string> = {}): URLSearchParams {
  return new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: REDIRECT_URI,
    client_id: CLIENT_ID,
    client_secret: CLIENT_SECRET,
    code_verifier: VERIFIER,
    ...overrides,
  });
}

describe('the fake Entra provider', () => {
  it('gives a code and the state back, and an id token with the claims Entra sends', async () => {
    const { location } = fake.authorize(request(), { oid: OID_ADVISOR, roles: ['DIUCS.Advisor'] });
    expect(new URL(location).searchParams.get('state')).toBe('state-1');
    const result = await fake.token(DIRECTORY_A, form(codeOf(location)));
    expect(result.status).toBe(200);
    const claims = decodeJwt(String(result.body.id_token));
    expect(claims).toMatchObject({ aud: CLIENT_ID, tid: DIRECTORY_A, oid: OID_ADVISOR, nonce: 'nonce-1', ver: '2.0' });
    expect(claims.iss).toBe(`${HOST}/${DIRECTORY_A}/v2.0`);
    expect(decodeProtectedHeader(String(result.body.id_token)).alg).toBe('RS256');
  });

  it.each([
    ['a missing code challenge', { code_challenge: '' }],
    ['a plain challenge method', { code_challenge_method: 'plain' }],
    ['a missing nonce', { nonce: '' }],
    ['a missing state', { state: '' }],
    ['another redirect address', { redirect_uri: 'https://elsewhere.example.test/cb' }],
    ['another client', { client_id: 'not-the-client' }],
    ['a scope without openid', { scope: 'profile' }],
  ])('refuses an authorisation request with %s', (_name, overrides) => {
    const { location } = fake.authorize(request(overrides), { oid: OID_ADVISOR });
    expect(new URL(location).searchParams.get('error')).not.toBeNull();
    expect(new URL(location).searchParams.get('code')).toBeNull();
  });

  it('checks the PKCE verifier, the secret and the redirect address at the token endpoint', async () => {
    const issue = () => codeOf(fake.authorize(request(), { oid: OID_ADVISOR }).location);
    expect((await fake.token(DIRECTORY_A, form(issue(), { code_verifier: 'w'.repeat(43) }))).status).toBe(400);
    expect((await fake.token(DIRECTORY_A, form(issue(), { client_secret: 'wrong' }))).status).toBe(401);
    expect((await fake.token(DIRECTORY_A, form(issue(), { redirect_uri: 'https://x.example.test/' }))).status).toBe(400);
    expect((await fake.token(DIRECTORY_B, form(issue()))).status).toBe(400);
  });

  it('accepts a code once', async () => {
    const code = codeOf(fake.authorize(request(), { oid: OID_ADVISOR }).location);
    expect((await fake.token(DIRECTORY_A, form(code))).status).toBe(200);
    expect((await fake.token(DIRECTORY_A, form(code))).status).toBe(400);
  });

  it('records what it was sent', async () => {
    const before = fake.recorded('token').length;
    await fake.token(DIRECTORY_A, form('unknown-code'));
    const last = fake.recorded('token').at(-1);
    expect(fake.recorded('token')).toHaveLength(before + 1);
    expect(last?.params.client_secret).toBe(CLIENT_SECRET);
  });
});
