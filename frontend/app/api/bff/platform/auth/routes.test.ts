// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE } from '@/lib/auth/session';
import { OPERATOR_COOKIE, unsealOperatorSession } from '@/lib/operator/session';
import { cookieWrites, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { authHandlers, resetExchanges, seenExchanges } from '@/test/msw/handlers/auth';
import { server } from '@/test/msw/server';
import {
  BACKEND_ROOT,
  DIRECTORY_A,
  DIRECTORY_PLATFORM,
  HOST,
  OID_OPERATOR,
  OID_SUPPORT,
  OPERATOR_CLIENT_ID,
  OPERATOR_CLIENT_SECRET,
  OPERATOR_ENV,
  OPERATOR_HOST_NAME,
  OPERATOR_PUBLIC_URL,
  OPERATOR_REDIRECT_URI,
} from '@/test/oidc/constants';
import { FakeEntra, type FakeUser } from '@/test/oidc/fake-entra';
import { entraHandlers } from '@/test/msw/handlers/entra';
import { resetKeyCache } from '@/lib/auth/oidc';
import { GET as callback } from './callback/route';
import { POST as start } from './start/route';

// The operator console's sign-in (TEN-083): the same authorisation code flow with PKCE as the staff
// sign-in, against the operator's own app registration and directory, served on its own host. It makes
// an OPERATOR session (no tenant) and never a tenant session; a customer's directory, a tenant role and a
// request on a tenant's host make nothing.

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const TRANSACTION_COOKIE = 'diucs_op_oidc';
const START_URL = `${OPERATOR_PUBLIC_URL}/api/bff/platform/auth/start`;
let fake: FakeEntra;

beforeEach(async () => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
  for (const [name, value] of Object.entries(OPERATOR_ENV)) vi.stubEnv(name, value);
  resetCookieWrites();
  resetExchanges();
  server.use(...authHandlers);
  fake = await FakeEntra.create({
    host: HOST,
    clientId: OPERATOR_CLIENT_ID,
    clientSecret: OPERATOR_CLIENT_SECRET,
    redirectUri: OPERATOR_REDIRECT_URI,
    directories: [DIRECTORY_PLATFORM, DIRECTORY_A],
  });
  server.use(...entraHandlers(fake));
  resetKeyCache();
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

function startRequest(fields: Record<string, string> = {}, url = START_URL): Request {
  return new Request(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Host: new URL(url).host },
    body: new URLSearchParams(fields).toString(),
  });
}

async function signIn(user: FakeUser, options: { fields?: Record<string, string>; host?: string } = {}) {
  const begun = await start(startRequest(options.fields));
  const authorize = begun.headers.get('location') ?? '';
  const sealed = lastWrite(TRANSACTION_COOKIE)?.value ?? '';
  const { location } = fake.authorize(authorize, user);
  resetCookieWrites();
  const host = options.host ?? OPERATOR_HOST_NAME;
  const url = new URL(location);
  const response = await callback(requestWithCookies(`https://${host}${url.pathname}${url.search}`, sealed ? { [TRANSACTION_COOKIE]: sealed } : {}, { headers: { Host: host } }));
  const write = lastWrite(OPERATOR_COOKIE);
  return {
    response,
    body: await response.text(),
    location: response.headers.get('location'),
    session: write && write.value ? await unsealOperatorSession(write.value) : null,
    write,
  };
}

describe('POST /api/bff/platform/auth/start', () => {
  it('sends the browser to the operator directory itself, with the operator’s client, its own callback, state, nonce and PKCE', async () => {
    const response = await start(startRequest());
    expect(response.status).toBe(303);
    const location = new URL(response.headers.get('location') ?? '');
    expect(location.pathname).toBe(`/${DIRECTORY_PLATFORM}/oauth2/v2.0/authorize`);
    expect(location.searchParams.get('client_id')).toBe(OPERATOR_CLIENT_ID);
    expect(location.searchParams.get('redirect_uri')).toBe(OPERATOR_REDIRECT_URI);
    for (const name of ['state', 'nonce', 'code_challenge']) expect(location.searchParams.get(name)).toBeTruthy();
    expect(location.searchParams.get('code_challenge_method')).toBe('S256');
    expect(response.headers.get('cache-control')).toBe('no-store');
  });

  it('keeps the transaction in a sealed cookie of its own, on its own path, Lax and short', async () => {
    await start(startRequest());
    const cookie = lastWrite(TRANSACTION_COOKIE);
    expect(cookie?.options).toMatchObject({ httpOnly: true, secure: true, sameSite: 'lax', path: '/api/bff/platform/auth' });
    expect(Number(cookie?.options.maxAge)).toBeGreaterThan(0);
    expect(Number(cookie?.options.maxAge)).toBeLessThanOrEqual(600);
    expect(cookie?.name).not.toBe('diucs_oidc');
  });

  it('takes no tenant, directory, role or hint from the request', async () => {
    const response = await start(
      startRequest({ tenant: 'trust-b', tid: DIRECTORY_A, directory: DIRECTORY_A, role: 'platform-operator', login_hint: 'x' }, `${START_URL}?tenant=trust-b&tid=${DIRECTORY_A}`),
    );
    const location = new URL(response.headers.get('location') ?? '');
    expect(location.pathname).toBe(`/${DIRECTORY_PLATFORM}/oauth2/v2.0/authorize`);
    expect(location.toString()).not.toContain('trust-b');
    expect(location.toString()).not.toContain(DIRECTORY_A);
  });

  it('is the failed sign-in page, with no redirect to the provider, for a request on a tenant’s host', async () => {
    const response = await start(startRequest({}, 'https://tenant-a.example.test/api/bff/platform/auth/start'));
    expect(response.headers.get('location')).toBe('/operator/sign-in?error=failed');
    expect(lastWrite(TRANSACTION_COOKIE)).toBeUndefined();
  });

  it.each(['OPERATOR_ENTRA_CLIENT_ID', 'OPERATOR_ENTRA_CLIENT_SECRET', 'OPERATOR_ENTRA_DIRECTORY_ID', 'DIUCS_OPERATOR_PUBLIC_URL'])(
    'is the failed sign-in page when %s is not set: the operator door fails closed',
    async (name) => {
      vi.stubEnv(name, '');
      const response = await start(startRequest());
      expect(response.headers.get('location')).toBe('/operator/sign-in?error=failed');
      expect(lastWrite(TRANSACTION_COOKIE)).toBeUndefined();
    },
  );

  it('does not fall back to the tenants’ app registration or to a shared endpoint', async () => {
    vi.stubEnv('OPERATOR_ENTRA_CLIENT_ID', '');
    vi.stubEnv('ENTRA_CLIENT_ID', OPERATOR_CLIENT_ID);
    vi.stubEnv('ENTRA_CLIENT_SECRET', OPERATOR_CLIENT_SECRET);
    vi.stubEnv('DIUCS_PUBLIC_URL', OPERATOR_PUBLIC_URL);
    expect((await start(startRequest())).headers.get('location')).toBe('/operator/sign-in?error=failed');
  });
});

describe('GET /api/bff/platform/auth/callback', () => {
  it('makes an operator session: the role the back end gave, no tenant, the host it was made on, and no tenant session', async () => {
    const outcome = await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM });
    expect(outcome.session).toMatchObject({ role: 'platform-operator', host: OPERATOR_HOST_NAME });
    expect(outcome.session?.accountRef).toMatch(/^ops-[0-9a-f]{32}$/);
    expect(outcome.session).not.toHaveProperty('tenantId');
    expect(new Set(cookieWrites.map((w) => w.name))).toEqual(new Set([OPERATOR_COOKIE, TRANSACTION_COOKIE]));
    expect(cookieWrites.some((w) => w.name === SESSION_COOKIE)).toBe(false);
    expect(outcome.write?.options).toMatchObject({ httpOnly: true, secure: true, sameSite: 'strict', path: '/' });
    expect(Number(outcome.write?.options.maxAge)).toBeLessThanOrEqual(3600);
  });

  it('asks the back end once, with the ID token as the only thing sent and the operator host as the host', async () => {
    await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM });
    expect(seenExchanges).toHaveLength(1);
    expect(seenExchanges[0]).toMatchObject({ path: '/auth/operator-token', host: OPERATOR_HOST_NAME, authorization: null });
    expect(Object.keys(seenExchanges[0]!.body as object)).toEqual(['idToken']);
  });

  it('keeps the Entra object id, the name and the ID token out of the cookie and the answer', async () => {
    const outcome = await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM });
    const everything = JSON.stringify([outcome.session, outcome.body, [...outcome.response.headers.entries()]]);
    expect(everything).not.toContain(OID_OPERATOR);
    expect(everything).not.toMatch(/Sample Staff|sample\.staff@example\.test/);
  });

  it('answers with a page that moves the browser on, to the operator home, and never a redirect', async () => {
    const outcome = await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM });
    expect(outcome.response.status).toBe(200);
    expect(outcome.location).toBeNull();
    expect(outcome.body).toContain('url=/operator"');
    expect(outcome.response.headers.get('cache-control')).toBe('no-store');
  });

  it('signs a support person in and sends them to the support requests', async () => {
    const outcome = await signIn({ oid: OID_SUPPORT, roles: ['DIUCS.Support'], tid: DIRECTORY_PLATFORM });
    expect(outcome.session?.role).toBe('support');
    expect(outcome.body).toContain('url=/operator/support"');
  });

  it('goes to next only when it is an operator page the role may open, and otherwise to the home', async () => {
    const good = await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM }, { fields: { next: '/operator/audit' } });
    expect(good.body).toContain('url=/operator/audit"');
    for (const next of ['/lead', '/admin', 'https://evil.example/', '//evil.example', '/operator/support']) {
      const outcome = await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM }, { fields: { next } });
      expect(outcome.body, next).toContain('url=/operator"');
    }
  });

  it('gives no session and the one access message for a person the back end refuses (a customer’s directory, no operator role)', async () => {
    for (const user of [
      { oid: OID_OPERATOR, roles: ['DIUCS.Lead'], tid: DIRECTORY_PLATFORM },
      { oid: OID_OPERATOR, roles: ['DIUCS.TenantAdmin'], tid: DIRECTORY_PLATFORM },
      { oid: OID_OPERATOR, roles: undefined, tid: DIRECTORY_PLATFORM },
    ] as FakeUser[]) {
      const outcome = await signIn(user);
      expect(outcome.session).toBeNull();
      expect(outcome.write).toBeUndefined();
      expect(outcome.location).toBe('/operator/sign-in?error=no-access');
    }
  });

  it('sends a person of a customer’s directory away as a failed sign-in: the app registration is for the operator directory only', async () => {
    const outcome = await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_A });
    expect(outcome.session).toBeNull();
    expect(outcome.location).toBe('/operator/sign-in?error=failed');
    expect(seenExchanges).toHaveLength(0);
  });

  it('is a failed sign-in, not the access message, when the back end fails, answers a tenant role or a token that is no operator’s', async () => {
    server.use(http.post(`${BACKEND_ROOT}/auth/operator-token`, () => HttpResponse.json({}, { status: 503 })));
    const failed = await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM });
    expect(failed.location).toBe('/operator/sign-in?error=failed');
    server.use(http.post(`${BACKEND_ROOT}/auth/operator-token`, () => HttpResponse.json({ token: 'a.b.c', expiresAt: '2030-01-01T00:00:00Z', role: 'lead' })));
    const wrong = await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM });
    expect(wrong.location).toBe('/operator/sign-in?error=failed');
    expect(wrong.write).toBeUndefined();
  });

  it('makes nothing on a tenant’s host, and does not ask the back end', async () => {
    const outcome = await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM }, { host: 'tenant-a.example.test' });
    expect(outcome.session).toBeNull();
    expect(outcome.location).toBe('/operator/sign-in?error=failed');
    expect(seenExchanges).toHaveLength(0);
  });

  it('refuses a callback with no transaction cookie, and a transaction that is the staff sign-in’s', async () => {
    const begun = await start(startRequest());
    const { location } = fake.authorize(begun.headers.get('location') ?? '', { oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM });
    const url = new URL(location);
    const back = (cookies: Record<string, string>) =>
      callback(requestWithCookies(`${OPERATOR_PUBLIC_URL}${url.pathname}${url.search}`, cookies, { headers: { Host: OPERATOR_HOST_NAME } }));
    resetCookieWrites();
    expect((await back({})).headers.get('location')).toBe('/operator/sign-in?error=failed');
    expect((await back({ diucs_oidc: lastWrite(TRANSACTION_COOKIE)?.value ?? 'x' })).headers.get('location')).toBe('/operator/sign-in?error=failed');
    expect(seenExchanges).toHaveLength(0);
  });

  it('logs one fixed word and never a token, a code or a claim', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    server.use(http.post(`${BACKEND_ROOT}/auth/operator-token`, () => HttpResponse.json({}, { status: 500 })));
    await signIn({ oid: OID_OPERATOR, roles: ['DIUCS.PlatformOperator'], tid: DIRECTORY_PLATFORM });
    expect(warn.mock.calls).toEqual([['operator sign-in refused: exchange-failed']]);
  });
});
