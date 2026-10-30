// @vitest-environment node
import { hkdfSync } from 'node:crypto';
import { decodeJwt, EncryptJWT, jwtDecrypt } from 'jose';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { unsealSession, SESSION_COOKIE } from '@/lib/auth/session';
import { cookieWrites, lastWrite, resetCookieWrites, requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { authHandlers, resetExchanges, seenExchanges } from '@/test/msw/handlers/auth';
import { server } from '@/test/msw/server';
import { http, HttpResponse } from 'msw';
import {
  BACKEND_ROOT,
  CLIENT_SECRET,
  DIRECTORY_A,
  DIRECTORY_B,
  DIRECTORY_PLATFORM,
  DIRECTORY_UNBOUND,
  ENTRA_ENV,
  OID_ADVISOR,
  OID_B,
  OID_LEAD,
  PUBLIC_URL,
  SIGN_IN_HOST,
} from '@/test/oidc/constants';
import type { FakeEntra, FakeUser, Tamper } from '@/test/oidc/fake-entra';
import { startFakeEntra, stubEntraEnv } from '@/test/oidc/harness';
import { standInToken, tenantOfHost } from '@/test/fixtures/exchange';
import { GET as callback } from './callback/route';
import { POST as start } from './start/route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const TRANSACTION_COOKIE = 'diucs_oidc';
const START_URL = `${PUBLIC_URL}/api/bff/auth/entra/start`;
const OTHER_HOST = 'trust-b.example.test';
const OID_B_USER = OID_B;

let fake: FakeEntra;

beforeEach(async () => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  stubEntraEnv();
  resetCookieWrites();
  resetExchanges();
  server.use(...authHandlers);
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

  it('asks the configured directory itself when the app registration is for one directory', async () => {
    stubEntraEnv({ ENTRA_DIRECTORY_ID: DIRECTORY_A });
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
        { tenant: 'trust-b', tenantId: 'trust-b', tid: DIRECTORY_B, directory: DIRECTORY_B, login_hint: 'x', domain_hint: 'y', role: 'lead', client_id: 'other' },
        `?tenant=trust-b&tid=${DIRECTORY_B}&directory=${DIRECTORY_B}&role=lead&redirect_uri=https://evil.example`,
      ),
    );
    const location = new URL(response.headers.get('location') ?? '');
    expect(location.pathname).toBe('/organizations/oauth2/v2.0/authorize');
    expect(location.searchParams.get('client_id')).toBe(ENTRA_ENV.ENTRA_CLIENT_ID);
    expect(location.searchParams.get('redirect_uri')).toBe(`${PUBLIC_URL}/api/bff/auth/entra/callback`);
    expect([...location.searchParams.keys()].sort()).toEqual(
      ['client_id', 'code_challenge', 'code_challenge_method', 'nonce', 'prompt', 'redirect_uri', 'response_mode', 'response_type', 'scope', 'state'],
    );
    expect(location.toString()).not.toContain('trust-b');
    expect(location.toString()).not.toContain(DIRECTORY_B);
  });

  it('treats a body that is not a form as having no next', async () => {
    const response = await start(
      new Request(START_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"next":"/lead"}' }),
    );
    expect(response.status).toBe(303);
    expect(new URL(response.headers.get('location') ?? '').pathname).toBe('/organizations/oauth2/v2.0/authorize');
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
    expect(outcome.session).toMatchObject({ role: 'advisor', services: [], host: SIGN_IN_HOST, tenantId: tenantOfHost(SIGN_IN_HOST) });
    expect(outcome.session?.sub).toMatch(/^stf-[0-9a-f]{32}$/);
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

  it('keeps the back end’s own token in the session, makes none, and ends the session when the token ends', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    const claims = decodeJwt(outcome.session!.backendToken);
    expect(claims).toMatchObject({ role: 'advisor', aud: 'diucs-api', services: [] });
    expect(claims.sub).toBe(outcome.session!.sub);
    expect(Date.parse(outcome.session!.expiresAt)).toBe(claims.exp! * 1000);
  });

  it('asks the back end once, with the ID token as the only thing in the body, and keeps the Entra object id out of the session', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    expect(seenExchanges).toHaveLength(1);
    expect(seenExchanges[0]).toMatchObject({ path: '/auth/token', host: SIGN_IN_HOST, authorization: null });
    expect(Object.keys(seenExchanges[0]!.body as object)).toEqual(['idToken']);
    expect(JSON.stringify(outcome.session)).not.toContain(OID_ADVISOR);
  });

  it('keeps the person’s name, email, the access token and the ID token out of the session, the cookie and the response', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    const { payload } = await jwtDecrypt(outcome.sessionWrite!.value, new Uint8Array(Buffer.from(TEST_SESSION_SECRET, 'base64')));
    const everything = JSON.stringify([payload, outcome.body, [...outcome.response.headers.entries()], cookieWrites.map((w) => w.options)]);
    expect(everything).not.toMatch(/Sample Staff|sample\.staff@example\.test|fake-access-token|id_token|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]/);
    expect(Object.keys(payload).sort()).toEqual(['backendToken', 'exp', 'expiresAt', 'host', 'iat', 'role', 'services', 'sub', 'tenantId']);
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

  it('never makes a support session here: the operator console has its own door (TEN-043), from any directory', async () => {
    for (const tid of [DIRECTORY_PLATFORM, DIRECTORY_A]) {
      resetCookieWrites();
      const outcome = await signIn({ oid: OID_LEAD, roles: ['DIUCS.Support'], tid });
      expectNoSession(outcome);
      expect(outcome.location).toBe('/sign-in?error=no-access');
    }
  });

  it('gives no session to a role this front end has no pages for yet, and says the access message', async () => {
    const outcome = await signIn({ oid: OID_LEAD, roles: ['DIUCS.TenantAdmin'], tid: DIRECTORY_A });
    expectNoSession(outcome);
    expect(outcome.location).toBe('/sign-in?error=no-access');
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

  it('gives the one access message to a person from a directory the host’s tenant has not bound: no session, no hint why', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_UNBOUND }, { fields: {} });
    expectNoSession(outcome);
    expect(outcome.location).toBe('/sign-in?error=no-access');
    const other = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_B });
    expect(other.location).toBe(outcome.location);
    expect(other.body).toBe(outcome.body);
  });

  it('sends a person from another directory away, as a failed sign-in, when the app registration is for one directory', async () => {
    stubEntraEnv({ ENTRA_DIRECTORY_ID: DIRECTORY_A });
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_UNBOUND });
    expectNoSession(outcome);
    expect(outcome.location).toBe('/sign-in?error=failed');
    expect(seenExchanges).toHaveLength(0);
  });

  it.each([404, 429, 500, 503])('gives a failed sign-in, not the access message, when the back end answers %i', async (status) => {
    server.use(http.post(`${BACKEND_ROOT}/auth/token`, () => HttpResponse.json({}, { status })));
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    expectNoSession(outcome);
    expect(outcome.location).toBe('/sign-in?error=failed');
  });

  it('gives a failed sign-in when the back end cannot be reached, and logs one fixed word', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    server.use(http.post(`${BACKEND_ROOT}/auth/token`, () => HttpResponse.error()));
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    expectNoSession(outcome);
    expect(outcome.location).toBe('/sign-in?error=failed');
    expect(warn.mock.calls).toEqual([['staff sign-in refused: exchange-failed']]);
  });

  it('does not ask the back end for a sign-in whose own checks failed (state, nonce, audience)', async () => {
    await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A }, { tamper: { nonce: 'bad' } });
    await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A }, { state: 'wrong' });
    expect(seenExchanges).toHaveLength(0);
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

  it('refuses a code that is far too long, without redeeming it', async () => {
    const begun = await start(startRequest());
    const sealed = lastWrite(TRANSACTION_COOKIE)!.value;
    const { location } = fake.authorize(begun.headers.get('location')!, USER);
    const long = new URL(location);
    long.searchParams.set('code', 'x'.repeat(3000));
    await refused(await outcomeOf(await callback(requestWithCookies(long.toString(), { [TRANSACTION_COOKIE]: sealed }))));
    expect(fake.recorded('token')).toHaveLength(0);
  });

  it('answers a fault (here, no session secret) as a failed sign-in, and logs only a fixed word', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const begun = await start(startRequest());
    const sealed = lastWrite(TRANSACTION_COOKIE)!.value;
    const { location } = fake.authorize(begun.headers.get('location')!, USER);
    vi.stubEnv('SESSION_SECRET', '');
    resetCookieWrites();
    const response = await callback(requestWithCookies(location, { [TRANSACTION_COOKIE]: sealed }));
    expect(response.headers.get('location')).toBe('/sign-in?error=failed');
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
    expect(warn.mock.calls).toEqual([['staff sign-in refused: fault']]);
  });

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

  it.each([
    ['a state that is not text', { state: 7 }],
    ['a state of the wrong shape', { state: 'short' }],
    ['a nonce of the wrong shape', { nonce: 'short' }],
    ['a verifier of the wrong shape', { verifier: 'short' }],
    ['a next that is not a path', { next: 'https://evil.example' }],
    ['a next that is not text', { next: 7 }],
  ])('refuses a transaction cookie that is ours but holds %s', async (_name, change) => {
    const begun = await start(startRequest());
    const { location } = fake.authorize(begun.headers.get('location')!, USER);
    const good = { state: 's'.repeat(43), nonce: 'n'.repeat(43), verifier: 'v'.repeat(43), next: '' };
    // The same key and format as lib/auth/flow.ts, to show that a well-sealed but wrong cookie is refused.
    const key = new Uint8Array(
      hkdfSync('sha256', new Uint8Array(Buffer.from(TEST_SESSION_SECRET, 'base64')), 'diucs-staff-sign-in', 'transaction-cookie-v1', 32),
    );
    const sealed = await new EncryptJWT({ ...good, ...change })
      .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
      .setExpirationTime('10m')
      .encrypt(key);
    resetCookieWrites();
    const back = new URL(location);
    back.searchParams.set('state', good.state);
    await refused(await outcomeOf(await callback(requestWithCookies(back.toString(), { [TRANSACTION_COOKIE]: sealed }))));
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

describe('tenant: it is the host the browser came to, decided by the back end, and nothing else', () => {
  const as = (oid: string, tid: string, roles = ['DIUCS.Advisor']): FakeUser => ({ oid, roles, tid });

  async function callbackOn(host: string, user: FakeUser, extra: Record<string, string> = {}) {
    const begun = await start(startRequest());
    const sealed = lastWrite(TRANSACTION_COOKIE)!.value;
    const { location } = fake.authorize(begun.headers.get('location')!, user);
    resetCookieWrites();
    const response = await callback(requestWithCookies(location, { [TRANSACTION_COOKIE]: sealed }, { headers: { Host: host, ...extra } }));
    const write = lastWrite(SESSION_COOKIE);
    return { response, session: write ? await unsealSession(write.value) : null };
  }

  it('sends the host the callback came to, so each tenant’s host gets that tenant’s answer for the same person', async () => {
    const a = await callbackOn(SIGN_IN_HOST, as(OID_ADVISOR, DIRECTORY_A));
    expect(a.session?.role).toBe('advisor');
    expect(seenExchanges.at(-1)?.host).toBe(SIGN_IN_HOST);
    // A member of directory A on the host that has bound directory B: the one refusal, no session.
    const wrong = await callbackOn(OTHER_HOST, as(OID_ADVISOR, DIRECTORY_A));
    expect(wrong.session).toBeNull();
    expect(wrong.response.headers.get('location')).toBe('/sign-in?error=no-access');
    expect(seenExchanges.at(-1)?.host).toBe(OTHER_HOST);
    const b = await callbackOn(OTHER_HOST, as(OID_B_USER, DIRECTORY_B));
    expect(b.session?.role).toBe('advisor');
    expect(b.session?.backendToken).not.toBe(a.session?.backendToken);
  });

  it('makes the session for the tenant the back end signed the token for, and for the host the callback came to (TEN-044)', async () => {
    const a = await callbackOn(SIGN_IN_HOST, as(OID_ADVISOR, DIRECTORY_A));
    const b = await callbackOn(OTHER_HOST, as(OID_B_USER, DIRECTORY_B));
    expect(a.session).toMatchObject({ tenantId: tenantOfHost(SIGN_IN_HOST), host: SIGN_IN_HOST });
    expect(b.session).toMatchObject({ tenantId: tenantOfHost(OTHER_HOST), host: OTHER_HOST });
    expect(a.session?.tenantId).not.toBe(b.session?.tenantId);
    expect(decodeJwt(a.session!.backendToken).tenant).toBe(a.session?.tenantId);
  });

  it('makes no session from a token that names no tenant, a network or a malformed tenant, and says the sign-in failed', async () => {
    for (const tenant of [undefined, '', 'net-capacity', 'Trust A', 7]) {
      resetCookieWrites();
      server.use(
        http.post(`${BACKEND_ROOT}/auth/token`, () => {
          const exp = Math.floor(Date.now() / 1000) + 3600;
          const token = standInToken({ sub: 'stf-0123456789abcdef0123456789abcdef', role: 'advisor', services: [], tenant, epoch: 1, aud: 'diucs-api', iat: exp - 3600, exp });
          return HttpResponse.json({ token, expiresAt: new Date(exp * 1000).toISOString(), role: 'advisor' });
        }),
      );
      const outcome = await callbackOn(SIGN_IN_HOST, as(OID_ADVISOR, DIRECTORY_A));
      expect(outcome.session, String(tenant)).toBeNull();
      expect(outcome.response.headers.get('location')).toBe('/sign-in?error=failed');
    }
  });

  it('keeps the same person apart on two hosts: the subject the back end derives differs', async () => {
    const a = await callbackOn('shared.example.test', as(OID_ADVISOR, DIRECTORY_A));
    const b = await callbackOn(SIGN_IN_HOST, as(OID_ADVISOR, DIRECTORY_A));
    expect(a.session?.sub).not.toBe(b.session?.sub);
  });

  it.each([
    ['tenant', 'trust-b'],
    ['tid', DIRECTORY_B],
    ['tenantId', 'trust-b'],
    ['directory', DIRECTORY_B],
    ['host', OTHER_HOST],
    ['organization', DIRECTORY_B],
  ])('ignores %s=%s in the callback query and in the start body', async (name, value) => {
    const outcome = await signIn(as(OID_ADVISOR, DIRECTORY_A), { callbackQuery: { [name]: value }, fields: { [name]: value } });
    expect(outcome.session?.role).toBe('advisor');
    expect(seenExchanges.at(-1)?.host).toBe(SIGN_IN_HOST);
    expect(Object.keys(seenExchanges.at(-1)!.body as object)).toEqual(['idToken']);
  });

  it.each([
    ['X-Tenant-Id', 'trust-b'],
    ['X-Forwarded-Host', OTHER_HOST],
    ['Forwarded', `host=${OTHER_HOST}`],
    ['X-Original-Host', OTHER_HOST],
  ])('ignores the %s header: only the Host the browser used names the tenant', async (name, value) => {
    const outcome = await callbackOn(SIGN_IN_HOST, as(OID_ADVISOR, DIRECTORY_A), { [name]: value });
    expect(outcome.session?.role).toBe('advisor');
    expect(seenExchanges.at(-1)?.host).toBe(SIGN_IN_HOST);
  });

  it('does not let a token signed for directory A pass as directory B’s, whatever its other claims say', async () => {
    const outcome = await signIn(as(OID_ADVISOR, DIRECTORY_B), { tamper: { iss: `${ENTRA_ENV.ENTRA_AUTHORITY_HOST}/${DIRECTORY_A}/v2.0` } });
    expectNoSession(outcome);
    expect(seenExchanges).toHaveLength(0);
  });
});

describe('what the sign-in logs', () => {
  it('logs no token, secret, code, state, nonce, verifier, object id, name, email or cookie value', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((level) => vi.spyOn(console, level).mockImplementation(() => {}));
    const good = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A }, { tamper: { nonce: 'bad' } });
    await signIn({ oid: OID_ADVISOR, roles: [], tid: DIRECTORY_A });
    await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_UNBOUND });
    await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Support'], tid: DIRECTORY_A });
    server.use(http.post(`${BACKEND_ROOT}/auth/token`, () => HttpResponse.json({}, { status: 503 })));
    await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    stubEntraEnv({ ENTRA_CLIENT_SECRET: undefined });
    await start(startRequest());

    const logged = spies.flatMap((spy) => spy.mock.calls).map((call) => call.map(String).join(' ')).join('\n');
    const authorize = fake.recorded('authorize').map((r) => r.params);
    const secrets = [
      CLIENT_SECRET,
      TEST_SESSION_SECRET,
      OID_ADVISOR,
      good.session?.sub ?? '',
      ...seenExchanges.map((e) => String((e.body as { idToken?: string }).idToken ?? '')),
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
