// @vitest-environment node
import { hkdfSync } from 'node:crypto';
import { EncryptJWT, jwtDecrypt } from 'jose';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { unsealSession, SESSION_COOKIE } from '@/lib/auth/session';
import { cookieWrites, lastWrite, resetCookieWrites, requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { http, HttpResponse } from 'msw';
import { claimsOf, fakeBackendToken } from '@/test/backendToken';
import { EXCHANGE_URL, resetExchanges, seenExchanges } from '@/test/msw/handlers/auth';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import {
  CLIENT_SECRET,
  DIRECTORY_A,
  DIRECTORY_B,
  DIRECTORY_UNBOUND,
  ENTRA_ENV,
  OID_ADVISOR,
  OID_LEAD,
  PUBLIC_URL,
  PUBLIC_URL_B,
  TENANT_A,
  TENANT_B,
} from '@/test/oidc/constants';
import type { FakeEntra, FakeUser, Tamper } from '@/test/oidc/fake-entra';
import { startFakeEntra, stubEntraEnv } from '@/test/oidc/harness';
import { GET as callback } from './callback/route';
import { POST as start } from './start/route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const TRANSACTION_COOKIE = 'diucs_oidc';
const START_PATH = '/api/bff/auth/entra/start';
const START_URL = `${PUBLIC_URL}${START_PATH}`;

let fake: FakeEntra;

beforeEach(async () => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', 'http://backend.test/fhir');
  // The front end holds no signing secret, no list of directories and no address of its own.
  for (const name of ['BACKEND_JWT_SECRET', 'DIUCS_ENTRA_BINDINGS', 'DIUCS_PUBLIC_URL']) vi.stubEnv(name, undefined as unknown as string);
  stubEntraEnv();
  resetCookieWrites();
  resetExchanges();
  fake = await startFakeEntra();
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function startRequest(fields: Record<string, string> = {}, query = '', site = PUBLIC_URL): Request {
  return new Request(`${site}${START_PATH}${query}`, {
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
  options: { fields?: Record<string, string>; tamper?: Tamper; callbackQuery?: Record<string, string>; state?: string; site?: string } = {},
): Promise<Outcome> {
  const site = options.site ?? PUBLIC_URL;
  const begun = await start(startRequest(options.fields, '', site));
  const authorize = begun.headers.get('location') ?? '';
  const sealed = lastWrite(TRANSACTION_COOKIE)?.value ?? '';
  const { location } = fake.authorize(authorize, user, options.tamper);
  const back = new URL(location);
  for (const [k, v] of Object.entries(options.callbackQuery ?? {})) back.searchParams.set(k, v);
  if (options.state !== undefined) back.searchParams.set('state', options.state);
  resetCookieWrites();
  const response = await callback(requestWithCookies(back.toString(), sealed ? { [TRANSACTION_COOKIE]: sealed } : {}, { headers: { Host: new URL(site).host } }));
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

  it('always asks the shared endpoint: the front end holds no list of directories, the back end binds them', async () => {
    const response = await start(startRequest());
    expect(new URL(response.headers.get('location') ?? '').pathname).toBe('/organizations/oauth2/v2.0/authorize');
  });

  it('sends the person back to the host they came from: one redirect address per tenant host', async () => {
    const a = new URL((await start(startRequest())).headers.get('location') ?? '');
    const b = new URL((await start(startRequest({}, '', PUBLIC_URL_B))).headers.get('location') ?? '');
    expect(a.searchParams.get('redirect_uri')).toBe(`${PUBLIC_URL}/api/bff/auth/entra/callback`);
    expect(b.searchParams.get('redirect_uri')).toBe(`${PUBLIC_URL_B}/api/bff/auth/entra/callback`);
  });

  it.each([
    ['a Host that is a path', 'tenant-a.example.test/evil'],
    ['a Host with a user', 'user@tenant-a.example.test'],
    ['a Host with a space', 'tenant-a .example.test'],
  ])('does not start for %s', async (_name, host) => {
    const request = new Request(START_URL, { method: 'POST', headers: { Host: host, 'Content-Type': 'application/x-www-form-urlencoded' }, body: '' });
    const response = await start(request);
    expect(response.headers.get('location')).toBe('/sign-in?error=failed');
    expect(lastWrite(TRANSACTION_COOKIE)).toBeUndefined();
  });

  it('takes the host from the Host header only, never from a forwarded header or the query', async () => {
    const request = new Request(`${START_URL}?host=${new URL(PUBLIC_URL_B).host}`, {
      method: 'POST',
      headers: { 'X-Forwarded-Host': new URL(PUBLIC_URL_B).host, Forwarded: `host=${new URL(PUBLIC_URL_B).host}`, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: '',
    });
    const location = new URL((await start(request)).headers.get('location') ?? '');
    expect(location.searchParams.get('redirect_uri')).toBe(`${PUBLIC_URL}/api/bff/auth/entra/callback`);
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
    expect(outcome.session).toMatchObject({ role: 'advisor', tenantId: TENANT_A, host: TENANTS.A.host, services: [] });
    expect(outcome.session?.sub).toEqual(expect.stringMatching(/^stf-/));
    expect(outcome.session?.sub).not.toBe(OID_ADVISOR);
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

  it('holds the token the back end issued for this host, and mints nothing itself', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    expect(seenExchanges).toHaveLength(1);
    expect(seenExchanges[0]?.host).toBe(TENANTS.A.host);
    expect(Object.keys(seenExchanges[0]?.body as object)).toEqual(['idToken']);
    expect(seenExchanges[0]?.authorization).toBeNull();
    const claims = claimsOf(outcome.session!.backendToken);
    expect(claims).toMatchObject({ tenant: TENANT_A, role: 'advisor', aud: 'diucs-api' });
    expect(Date.parse(outcome.session!.expiresAt)).toBe((claims.exp as number) * 1000);
  });

  it('works with no signing secret in the environment at all', async () => {
    expect(process.env.BACKEND_JWT_SECRET).toBeUndefined();
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], tid: DIRECTORY_A });
    expect(outcome.session).not.toBeNull();
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

  it('never gives the support role or any platform role on a tenant host, whatever the directory says', async () => {
    for (const roles of [['DIUCS.Support'], ['DIUCS.PlatformOperator'], ['DIUCS.Support', 'DIUCS.Advisor']]) {
      resetCookieWrites();
      const outcome = await signIn({ oid: OID_LEAD, roles, tid: DIRECTORY_A });
      if (roles.includes('DIUCS.Advisor')) {
        expect(outcome.session?.role).toBe('advisor');
      } else {
        expectNoSession(outcome);
        expect(outcome.location).toBe('/sign-in?error=no-access');
      }
    }
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

  it('gives a person from a directory this tenant has not bound the one refusal, the same as no role', async () => {
    const unbound = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_UNBOUND });
    expectNoSession(unbound);
    expect(unbound.location).toBe('/sign-in?error=no-access');
    const noRole = await signIn({ oid: OID_ADVISOR, roles: [], tid: DIRECTORY_A });
    expect(noRole.location).toBe(unbound.location);
    expect(noRole.response.status).toBe(unbound.response.status);
  });

  it('gives a member of another tenant’s directory nothing on this tenant’s host', async () => {
    const outcome = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_B });
    expectNoSession(outcome);
    expect(outcome.location).toBe('/sign-in?error=no-access');
  });

  it('answers a back end that is down, a host it does not know and an answer it cannot trust as a failed sign-in, with no session', async () => {
    server.use(http.post(EXCHANGE_URL, () => HttpResponse.json({}, { status: 503 })));
    const down = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_A });
    expectNoSession(down);
    expect(down.location).toBe('/sign-in?error=failed');

    server.use(http.post(EXCHANGE_URL, () => HttpResponse.json({}, { status: 404 })));
    const unknown = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_A });
    expectNoSession(unknown);
    expect(unknown.location).toBe('/sign-in?error=failed');

    server.use(http.post(EXCHANGE_URL, () => HttpResponse.json({ token: 'x', role: 'lead', expiresAt: 'tomorrow' })));
    const bad = await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_A });
    expectNoSession(bad);
    expect(bad.location).toBe('/sign-in?error=failed');
  });

  it.each(['wall', 'reporter', 'support', 'platform-operator', 'anonymous-link'])(
    'makes no session from a token for the role %s: that is not a staff sign-in',
    async (role) => {
      server.use(
        http.post(EXCHANGE_URL, () => {
          const exp = Math.floor(Date.now() / 1000) + 3600;
          return HttpResponse.json({ token: fakeBackendToken({ role, tenant: TENANT_A, exp }), role, expiresAt: new Date(exp * 1000).toISOString() });
        }),
      );
      expectNoSession(await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_A }));
    },
  );

  it('makes no session from a token for another tenant than the host’s answer claims, when the token names none', async () => {
    server.use(
      http.post(EXCHANGE_URL, () => {
        const exp = Math.floor(Date.now() / 1000) + 3600;
        return HttpResponse.json({ token: fakeBackendToken({ role: 'lead', tenant: undefined as unknown as string, exp }), role: 'lead', expiresAt: new Date(exp * 1000).toISOString() });
      }),
    );
    expectNoSession(await signIn({ oid: OID_ADVISOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_A }));
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
    ['no host', { host: undefined }],
    ['a host that is not a host name', { host: 'tenant-a.example.test/evil' }],
    ['another tenant’s host', { host: TENANTS.B.host }],
  ])('refuses a transaction cookie that is ours but holds %s', async (_name, change) => {
    const begun = await start(startRequest());
    const { location } = fake.authorize(begun.headers.get('location')!, USER);
    const good = { state: 's'.repeat(43), nonce: 'n'.repeat(43), verifier: 'v'.repeat(43), next: '', host: TENANTS.A.host };
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

describe('tenant: it comes from the host, through the back end, and from nothing else', () => {
  const as = (oid: string, tid: string, roles = ['DIUCS.Advisor']): FakeUser => ({ oid, roles, tid });

  it('is the tenant of each host, and the same object id on two hosts gives two sessions', async () => {
    const a = await signIn(as(OID_ADVISOR, DIRECTORY_A));
    const b = await signIn(as(OID_ADVISOR, DIRECTORY_B), { site: PUBLIC_URL_B });
    expect(a.session).toMatchObject({ tenantId: TENANT_A, host: TENANTS.A.host });
    expect(b.session).toMatchObject({ tenantId: TENANT_B, host: TENANTS.B.host });
    expect(claimsOf(a.session!.backendToken).tenant).toBe(TENANT_A);
    expect(claimsOf(b.session!.backendToken).tenant).toBe(TENANT_B);
    expect(a.session?.backendToken).not.toBe(b.session?.backendToken);
    expect(seenExchanges.map((e) => e.host)).toEqual([TENANTS.A.host, TENANTS.B.host]);
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
    expect(outcome.session?.tenantId).toBe(TENANT_A);
    expect(seenExchanges.at(-1)?.host).toBe(TENANTS.A.host);
  });

  it('ignores a tenant header and a forwarded host on the callback', async () => {
    const begun = await start(startRequest());
    const sealed = lastWrite(TRANSACTION_COOKIE)!.value;
    const { location } = fake.authorize(begun.headers.get('location')!, as(OID_ADVISOR, DIRECTORY_A));
    const response = await callback(
      requestWithCookies(location, { [TRANSACTION_COOKIE]: sealed }, { headers: { 'X-Tenant-Id': TENANT_B, 'X-Forwarded-Host': TENANTS.B.host, Host: TENANTS.A.host } }),
    );
    expect(response.status).toBe(200);
    expect((await unsealSession(lastWrite(SESSION_COOKIE)!.value))?.tenantId).toBe(TENANT_A);
    expect(seenExchanges.at(-1)?.host).toBe(TENANTS.A.host);
  });

  it('gives no session when a person of directory B signs in on tenant A’s host, even with a tenant B hint', async () => {
    const outcome = await signIn(as(OID_ADVISOR, DIRECTORY_B), { callbackQuery: { tenant: TENANT_B }, fields: { tenant: TENANT_B } });
    expectNoSession(outcome);
  });

  it('gives no session when the sign-in began on one host and comes back on another', async () => {
    const begun = await start(startRequest({}, '', PUBLIC_URL));
    const sealed = lastWrite(TRANSACTION_COOKIE)!.value;
    const { location } = fake.authorize(begun.headers.get('location')!, as(OID_ADVISOR, DIRECTORY_A));
    resetCookieWrites();
    const back = new URL(location);
    const response = await callback(requestWithCookies(back.toString(), { [TRANSACTION_COOKIE]: sealed }, { headers: { Host: TENANTS.B.host } }));
    expect(response.headers.get('location')).toBe('/sign-in?error=failed');
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
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
