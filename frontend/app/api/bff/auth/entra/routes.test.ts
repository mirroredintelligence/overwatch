// @vitest-environment node
import { jwtDecrypt, jwtVerify } from 'jose';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { unsealSession, SESSION_COOKIE } from '@/lib/auth/session';
import { cookieWrites, lastWrite, resetCookieWrites, requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import {
  BACKEND_JWT_SECRET,
  CLIENT_SECRET,
  DIRECTORY_A,
  DIRECTORY_B,
  DIRECTORY_PLATFORM,
  DIRECTORY_UNBOUND,
  ENTRA_ENV,
  OID_ADVISOR,
  OID_LEAD,
  PUBLIC_URL,
  SINGLE_BINDING,
  TENANT_A,
  TENANT_B,
  TENANT_PLATFORM,
} from '@/test/oidc/constants';
import type { FakeEntra, FakeUser, Tamper } from '@/test/oidc/fake-entra';
import { startFakeEntra, stubEntraEnv } from '@/test/oidc/harness';
import { GET as callback } from './callback/route';
import { POST as start } from './start/route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const TRANSACTION_COOKIE = 'diucs_oidc';
const START_URL = `${PUBLIC_URL}/api/bff/auth/entra/start`;
const BACKEND_KEY = new Uint8Array(Buffer.from(BACKEND_JWT_SECRET, 'base64'));

let fake: FakeEntra;

beforeEach(async () => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  stubEntraEnv();
  resetCookieWrites();
  fake = await startFakeEntra();
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function startRequest(fields: Record<string, string> = {}, query = ''): Request {
  return new Request(`${START_URL}${query}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(fields).toString(),
  });
}

type Outcome = {
  response: Response;
  body: string;
  location: string | null;
  session: Awaited<ReturnType<typeof unsealSession>>;
  sessionWrite: ReturnType<typeof lastWrite>;
  transactionWrites: typeof cookieWrites;
};

/**
 * One whole sign-in as the browser does it: POST start, follow the redirect to the fake provider,
 * the person signs in as `user`, come back to the callback with the transaction cookie.
 */
async function signIn(
  user: FakeUser,
  options: { fields?: Record<string, string>; tamper?: Tamper; callbackQuery?: Record<string, string>; state?: string } = {},
): Promise<Outcome> {
  const begun = await start(startRequest(options.fields));
  const authorize = begun.headers.get('location') ?? '';
  const sealed = lastWrite(TRANSACTION_COOKIE)?.value ?? '';
  const { location } = fake.authorize(authorize, user, options.tamper);
  const back = new URL(location);
  for (const [k, v] of Object.entries(options.callbackQuery ?? {})) back.searchParams.set(k, v);
  if (options.state !== undefined) back.searchParams.set('state', options.state);
  resetCookieWrites();
  const response = await callback(requestWithCookies(back.toString(), sealed ? { [TRANSACTION_COOKIE]: sealed } : {}));
  const sessionWrite = lastWrite(SESSION_COOKIE);
  return {
    response,
    body: await response.text(),
    location: response.headers.get('location'),
    session: sessionWrite && sessionWrite.value ? await unsealSession(sessionWrite.value) : null,
    sessionWrite,
    transactionWrites: cookieWrites.filter((w) => w.name === TRANSACTION_COOKIE),
  };
}

function expectNoSession(outcome: Outcome) {
  expect(outcome.sessionWrite).toBeUndefined();
  expect(outcome.session).toBeNull();
}

describe('POST /api/bff/auth/entra/start', () => {
  it('redirects the browser to the directory’s authorize endpoint with state, nonce and a PKCE challenge', async () => {
    const response = await start(startRequest());
    expect(response.status).toBe(303);
    const location = new URL(response.headers.get('location') ?? '');
    expect(location.origin + location.pathname).toMatch(/^https:\/\/login\.entra-fake\.test\/organizations\/oauth2\/v2\.0\/authorize$/);
    for (const name of ['state', 'nonce', 'code_challenge']) expect(location.searchParams.get(name)).toBeTruthy();
    expect(location.searchParams.get('code_challenge_method')).toBe('S256');
    expect(response.headers.get('cache-control')).toBe('no-store');
  });

  it('asks the bound directory itself when only one is bound', async () => {
    stubEntraEnv({ DIUCS_ENTRA_BINDINGS: SINGLE_BINDING });
    const response = await start(startRequest());
    expect(new URL(response.headers.get('location') ?? '').pathname).toBe(`/${DIRECTORY_A}/oauth2/v2.0/authorize`);
  });

  it('keeps the transaction in one sealed cookie: HttpOnly, Secure, SameSite Lax, limited path, short life', async () => {
    await start(startRequest());
    const cookie = lastWrite(TRANSACTION_COOKIE);
    expect(cookie?.options).toMatchObject({ httpOnly: true, secure: true, sameSite: 'lax', path: '/api/bff/auth/entra' });
    expect(Number(cookie?.options.maxAge)).toBeGreaterThan(0);
    expect(Number(cookie?.options.maxAge)).toBeLessThanOrEqual(600);
    // Sealed: the state, nonce and verifier are not readable in it.
    const location = new URL((await start(startRequest())).headers.get('location') ?? '');
    const state = location.searchParams.get('state') ?? '';
    expect(lastWrite(TRANSACTION_COOKIE)?.value).not.toContain(state);
    expect(Buffer.from(lastWrite(TRANSACTION_COOKIE)?.value.split('.')[0] ?? '', 'base64url').toString()).not.toContain('state');
  });

  it('uses a new state, nonce and challenge for every sign-in', async () => {
    const one = new URL((await start(startRequest())).headers.get('location') ?? '').searchParams;
    const two = new URL((await start(startRequest())).headers.get('location') ?? '').searchParams;
    for (const name of ['state', 'nonce', 'code_challenge']) expect(one.get(name)).not.toBe(two.get(name));
  });

  it('accepts no tenant, directory, hint or role from the request, in the body or the query', async () => {
    const response = await start(
      startRequest(
        { tenant: TENANT_B, tenantId: TENANT_B, tid: DIRECTORY_B, directory: DIRECTORY_B, login_hint: 'x', domain_hint: 'y', role: 'lead', client_id: 'other' },
        `?tenant=${TENANT_B}&tid=${DIRECTORY_B}&directory=${DIRECTORY_B}&role=lead&redirect_uri=https://evil.example`,
      ),
    );
    const location = new URL(response.headers.get('location') ?? '');
    expect(location.pathname).toBe('/organizations/oauth2/v2.0/authorize');
    expect(location.searchParams.get('client_id')).toBe(ENTRA_ENV.ENTRA_CLIENT_ID);
    expect(location.searchParams.get('redirect_uri')).toBe(`${PUBLIC_URL}/api/bff/auth/entra/callback`);
    expect([...location.searchParams.keys()].sort()).toEqual(
      ['client_id', 'code_challenge', 'code_challenge_method', 'nonce', 'prompt', 'redirect_uri', 'response_mode', 'response_type', 'scope', 'state'],
    );
    expect(location.toString()).not.toContain(TENANT_B);
    expect(location.toString()).not.toContain(DIRECTORY_B);
  });

  it('answers a missing setting with the failed-sign-in page and no redirect to the provider', async () => {
    stubEntraEnv({ ENTRA_CLIENT_SECRET: undefined });
    const response = await start(startRequest());
    expect(response.status).toBe(303);
    expect(response.headers.get('location')).toBe('/sign-in?error=failed');
    expect(lastWrite(TRANSACTION_COOKIE)).toBeUndefined();
  });
});

describe('GET /api/bff/auth/entra/callback: a good sign-in', () => {
  it('creates our own session cookie and no other session cookie, and clears the transaction cookie', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    expect(outcome.session).toMatchObject({ role: 'advisor', sub: OID_ADVISOR, services: [] });
    expect(new Set(cookieWrites.map((w) => w.name))).toEqual(new Set([SESSION_COOKIE, TRANSACTION_COOKIE]));
    expect(outcome.transactionWrites).toHaveLength(1);
    expect(outcome.transactionWrites[0]?.value).toBe('');
    expect(outcome.transactionWrites[0]?.options.maxAge).toBe(0);
  });

  it('sets the session cookie HttpOnly, Secure, SameSite Strict, for the life of the back-end token (8 hours)', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    expect(outcome.sessionWrite?.options).toMatchObject({ httpOnly: true, secure: true, sameSite: 'strict', path: '/' });
    expect(Number(outcome.sessionWrite?.options.maxAge)).toBeGreaterThan(8 * 3600 - 60);
    expect(Number(outcome.sessionWrite?.options.maxAge)).toBeLessThanOrEqual(8 * 3600);
  });

  it('mints a back-end token for the object id, the role and the tenant of the directory the person signed into', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    const { payload } = await jwtVerify(outcome.session!.backendToken, BACKEND_KEY, { algorithms: ['HS256'] });
    expect(payload).toMatchObject({ sub: OID_ADVISOR, role: 'advisor', tid: TENANT_A, services: [] });
    expect(Object.keys(payload).sort()).toEqual(['exp', 'iat', 'role', 'services', 'sub', 'tid']);
    expect(Date.parse(outcome.session!.expiresAt)).toBeCloseTo(payload.exp! * 1000, -3);
  });

  it('keeps the person’s name, email, the access token and the ID token out of the session, the cookie and the response', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    const { payload } = await jwtDecrypt(outcome.sessionWrite!.value, new Uint8Array(Buffer.from(TEST_SESSION_SECRET, 'base64')));
    const everything = JSON.stringify([payload, outcome.body, [...outcome.response.headers.entries()], cookieWrites.map((w) => w.options)]);
    expect(everything).not.toMatch(/Sample Staff|sample\.staff@example\.test|fake-access-token|id_token|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]/);
    expect(Object.keys(payload).sort()).toEqual(['backendToken', 'exp', 'expiresAt', 'iat', 'role', 'services', 'sub']);
  });

  it('answers with a page that moves the browser on, not a redirect, so the strict cookie is sent on the next request', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    expect(outcome.response.status).toBe(200);
    expect(outcome.location).toBeNull();
    expect(outcome.response.headers.get('content-type')).toContain('text/html');
    expect(outcome.response.headers.get('cache-control')).toBe('no-store');
    expect(outcome.response.headers.get('referrer-policy')).toBe('no-referrer');
    expect(outcome.body).toContain('http-equiv="refresh" content="0;url=/advisor"');
    expect(outcome.body).toContain('href="/advisor"');
  });

  it.each([
    ['advisor', ['DIUCS.Advisor'], 'advisor', '/advisor'],
    ['clinical', ['DIUCS.Clinical'], 'clinical', '/clinical'],
    ['lead', ['DIUCS.Lead'], 'lead', '/lead'],
    ['owner', ['DIUCS.Owner'], 'owner', '/owner/criteria'],
    ['exec', ['DIUCS.Planning'], 'exec', '/planning'],
    ['lead and advisor', ['DIUCS.Advisor', 'DIUCS.Lead'], 'lead', '/lead'],
  ])('signs in a %s and goes to their home', async (_name, roles, role, home) => {
    const outcome = await signIn({ oid: OID_LEAD, roles, tid: DIRECTORY_A });
    expect(outcome.session?.role).toBe(role);
    expect(outcome.body).toContain(`url=${home}"`);
  });

  it('goes to next when it is a same-origin path the role may open', async () => {
    const outcome = await signIn({ oid: OID_LEAD, roles: ['DIUCS.Lead'], tid: DIRECTORY_A }, { fields: { next: '/lead?tab=late' } });
    expect(outcome.body).toContain('url=/lead?tab=late"');
  });

  it.each(['https://evil.example/', '//evil.example', '/\\evil.example', 'javascript:alert(1)', '/lead"><script>x</script>'])(
    'goes to the role home, not to next=%s',
    async (next) => {
      const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A }, { fields: { next } });
      expect(outcome.body).toContain('url=/advisor"');
      expect(outcome.body).not.toContain('evil');
      expect(outcome.body).not.toContain('<script>');
    },
  );

  it('goes to the role home when next is a page the role may not open', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A }, { fields: { next: '/lead' } });
    expect(outcome.body).toContain('url=/advisor"');
  });

  it('gives the support role only from the operator’s own directory', async () => {
    const platform = await signIn({ oid: OID_LEAD, roles: ['DIUCS.Support'], tid: DIRECTORY_PLATFORM });
    expect(platform.session?.role).toBe('support');
    const { payload } = await jwtVerify(platform.session!.backendToken, BACKEND_KEY);
    expect(payload.tid).toBe(TENANT_PLATFORM);

    resetCookieWrites();
    const customer = await signIn({ oid: OID_LEAD, roles: ['DIUCS.Support'], tid: DIRECTORY_A });
    expectNoSession(customer);
    expect(customer.location).toBe('/sign-in?error=no-access');
  });
});

describe('GET /api/bff/auth/entra/callback: who may not sign in', () => {
  it.each([
    ['no roles claim', undefined],
    ['an empty roles claim', []],
    ['only roles DIUCS does not map', ['Some.Other.Role']],
  ])('gives no session and the access message page for %s', async (_name, roles) => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles, tid: DIRECTORY_A });
    expectNoSession(outcome);
    expect(outcome.response.status).toBe(303);
    expect(outcome.location).toBe('/sign-in?error=no-access');
    expect(outcome.transactionWrites[0]?.options.maxAge).toBe(0);
  });

  it('sends a person from a directory no tenant is bound to to the forbidden page, with no session', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_UNBOUND }, { fields: {} });
    expectNoSession(outcome);
    expect(outcome.location).toBe('/forbidden');
  });

  it('sends a person from an unbound directory away even with the single-directory setting, when the provider says so', async () => {
    stubEntraEnv({ DIUCS_ENTRA_BINDINGS: SINGLE_BINDING });
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_UNBOUND });
    expectNoSession(outcome);
    expect(outcome.location).toBe('/sign-in?error=failed');
  });
});

describe('GET /api/bff/auth/entra/callback: the checks that stop a forged or replayed sign-in', () => {
  const USER: FakeUser = { oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_A };

  async function refused(outcome: Outcome) {
    expectNoSession(outcome);
    expect(outcome.response.status).toBe(303);
    expect(outcome.location).toBe('/sign-in?error=failed');
  }

  it('refuses a state that is not the one it started with, and does not redeem the code', async () => {
    const outcome = await signIn(USER, { state: 'a-different-state' });
    await refused(outcome);
    expect(fake.recorded('token')).toHaveLength(0);
  });

  it('refuses a callback with no state, and one with no code', async () => {
    const begun = await start(startRequest());
    const sealed = lastWrite(TRANSACTION_COOKIE)!.value;
    const { location } = fake.authorize(begun.headers.get('location')!, USER);
    const noState = new URL(location);
    noState.searchParams.delete('state');
    await refused({ ...(await outcomeOf(await callback(requestWithCookies(noState.toString(), { [TRANSACTION_COOKIE]: sealed })))) });
    const noCode = new URL(location);
    noCode.searchParams.delete('code');
    await refused({ ...(await outcomeOf(await callback(requestWithCookies(noCode.toString(), { [TRANSACTION_COOKIE]: sealed })))) });
    expect(fake.recorded('token')).toHaveLength(0);
  });

  async function outcomeOf(response: Response): Promise<Outcome> {
    const sessionWrite = lastWrite(SESSION_COOKIE);
    return { response, body: await response.text(), location: response.headers.get('location'), session: null, sessionWrite, transactionWrites: [] };
  }

  it('refuses a callback that comes without the transaction cookie (another browser)', async () => {
    const begun = await start(startRequest());
    const { location } = fake.authorize(begun.headers.get('location')!, USER);
    resetCookieWrites();
    await refused(await outcomeOf(await callback(requestWithCookies(location, {}))));
    expect(fake.recorded('token')).toHaveLength(0);
  });

  it('refuses a transaction cookie that was changed or is not ours', async () => {
    const begun = await start(startRequest());
    const sealed = lastWrite(TRANSACTION_COOKIE)!.value;
    const { location } = fake.authorize(begun.headers.get('location')!, USER);
    for (const value of [sealed.slice(0, -4) + 'AAAA', 'garbage', '']) {
      resetCookieWrites();
      await refused(await outcomeOf(await callback(requestWithCookies(location, { [TRANSACTION_COOKIE]: value }))));
    }
    expect(fake.recorded('token')).toHaveLength(0);
  });

  it('refuses a transaction cookie older than ten minutes', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    const begun = await start(startRequest());
    const sealed = lastWrite(TRANSACTION_COOKIE)!.value;
    const { location } = fake.authorize(begun.headers.get('location')!, USER);
    vi.setSystemTime(Date.now() + 11 * 60_000);
    await refused(await outcomeOf(await callback(requestWithCookies(location, { [TRANSACTION_COOKIE]: sealed }))));
    expect(fake.recorded('token')).toHaveLength(0);
  });

  it('refuses a provider error, and does not repeat its description', async () => {
    const outcome = await signIn(USER, { callbackQuery: { error: 'access_denied', error_description: 'AADSTS-secret-text', code: '' } });
    await refused(outcome);
    expect(outcome.location).not.toContain('AADSTS');
    expect(outcome.body).not.toContain('AADSTS');
  });

  it('refuses a replayed callback: the code works once', async () => {
    const begun = await start(startRequest());
    const sealed = lastWrite(TRANSACTION_COOKIE)!.value;
    const { location } = fake.authorize(begun.headers.get('location')!, USER);
    const first = await callback(requestWithCookies(location, { [TRANSACTION_COOKIE]: sealed }));
    expect(first.status).toBe(200);
    resetCookieWrites();
    const second = await callback(requestWithCookies(location, { [TRANSACTION_COOKIE]: sealed }));
    expect(second.headers.get('location')).toBe('/sign-in?error=failed');
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
  });

  it.each([
    ['a nonce that is not ours', { nonce: 'a-different-nonce' }],
    ['the wrong audience', { aud: 'some-other-client' }],
    ['the wrong issuer', { iss: `https://login.other.test/${DIRECTORY_A}/v2.0` }],
    ['an expired token', { expiresIn: -300 }],
    ['a key the directory does not publish', { signWith: 'unpublished-key' as const }],
    ['alg none', { algorithm: 'none' as const }],
    ['HS256 with the client secret', { algorithm: 'HS256' as const }],
  ])('refuses a token with %s', async (_name, tamper) => {
    await refused(await signIn(USER, { tamper }));
  });
});

describe('tenant: it comes from the verified directory and from nothing else', () => {
  const as = (oid: string, tid: string, roles = ['DIUCS.Advisor']): FakeUser => ({ oid, roles, tid });

  it('mints the tenant of the directory for each of two directories, also for the same object id', async () => {
    const a = await signIn(as(OID_ADVISOR, DIRECTORY_A));
    const b = await signIn(as(OID_ADVISOR, DIRECTORY_B));
    const claimsA = (await jwtVerify(a.session!.backendToken, BACKEND_KEY)).payload;
    const claimsB = (await jwtVerify(b.session!.backendToken, BACKEND_KEY)).payload;
    expect(claimsA.tid).toBe(TENANT_A);
    expect(claimsB.tid).toBe(TENANT_B);
    expect(a.session?.backendToken).not.toBe(b.session?.backendToken);
  });

  it.each([
    ['tenant', TENANT_B],
    ['tid', TENANT_B],
    ['tenantId', TENANT_B],
    ['directory', DIRECTORY_B],
    ['organization', DIRECTORY_B],
    ['x-tenant-id', TENANT_B],
  ])('ignores %s=%s in the callback query and in the start body', async (name, value) => {
    const outcome = await signIn(as(OID_ADVISOR, DIRECTORY_A), { callbackQuery: { [name]: value }, fields: { [name]: value } });
    const { payload } = await jwtVerify(outcome.session!.backendToken, BACKEND_KEY);
    expect(payload.tid).toBe(TENANT_A);
  });

  it('ignores a tenant header on the callback', async () => {
    const begun = await start(startRequest());
    const sealed = lastWrite(TRANSACTION_COOKIE)!.value;
    const { location } = fake.authorize(begun.headers.get('location')!, as(OID_ADVISOR, DIRECTORY_A));
    const response = await callback(
      requestWithCookies(location, { [TRANSACTION_COOKIE]: sealed }, { headers: { 'X-Tenant-Id': TENANT_B, Host: 'trust-b.example.test' } }),
    );
    expect(response.status).toBe(200);
    const { payload } = await jwtVerify((await unsealSession(lastWrite(SESSION_COOKIE)!.value))!.backendToken, BACKEND_KEY);
    expect(payload.tid).toBe(TENANT_A);
  });

  it('does not let a token signed for directory A name tenant B, whatever its other claims say', async () => {
    const outcome = await signIn(as(OID_ADVISOR, DIRECTORY_B), { tamper: { iss: `${ENTRA_ENV.ENTRA_AUTHORITY_HOST}/${DIRECTORY_A}/v2.0` } });
    expectNoSession(outcome);
  });
});

describe('what the sign-in logs', () => {
  it('logs no token, secret, code, state, nonce, verifier, object id, name, email or cookie value', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((level) => vi.spyOn(console, level).mockImplementation(() => {}));
    const good = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A }, { tamper: { nonce: 'bad' } });
    await signIn({ oid: OID_ADVISOR, roles: [], tid: DIRECTORY_A });
    await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_UNBOUND });
    stubEntraEnv({ ENTRA_CLIENT_SECRET: undefined });
    await start(startRequest());

    const logged = spies.flatMap((spy) => spy.mock.calls).map((call) => call.map(String).join(' ')).join('\n');
    const authorize = fake.recorded('authorize').map((r) => r.params);
    const secrets = [
      CLIENT_SECRET,
      BACKEND_JWT_SECRET,
      TEST_SESSION_SECRET,
      OID_ADVISOR,
      'Sample Staff',
      'sample.staff@example.test',
      good.sessionWrite?.value ?? '',
      good.session?.backendToken ?? '',
      ...authorize.flatMap((p) => [p.state, p.nonce, p.code_challenge]),
      ...fake.recorded('token').flatMap((r) => [r.params.code, r.params.code_verifier]),
    ].filter(Boolean);
    expect(secrets.length).toBeGreaterThan(10);
    for (const secret of secrets) expect(logged).not.toContain(secret);
  });
});
