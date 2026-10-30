// @vitest-environment node
import { decodeJwt } from 'jose';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, unsealSession } from '@/lib/auth/session';
import { DEVICE_COOKIE, rememberDevice } from '@/lib/screens/cookies';
import { lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { authHandlers, resetExchanges, seenExchanges } from '@/test/msw/handlers/auth';
import { server } from '@/test/msw/server';
import { BACKEND_ROOT, SIGN_IN_HOST } from '@/test/oidc/constants';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// POST /api/bff/screens/session: a paired screen's wall token lasts an hour (TEN-043), so a screen
// that has opened (or lost its session) asks here for a new one, with the device token only this
// route reads. A screen the back end no longer knows is told so, and forgets its device token.

const URL_ = `https://${SIGN_IN_HOST}/api/bff/screens/session`;

async function deviceCookie(token = 'device-token-for-screen-one') {
  resetCookieWrites();
  await rememberDevice(token);
  const value = lastWrite(DEVICE_COOKIE)!.value;
  resetCookieWrites();
  return value;
}

function post(cookie: string | null, headers: Record<string, string> = {}) {
  return POST(requestWithCookies(URL_, cookie === null ? {} : { [DEVICE_COOKIE]: cookie }, { method: 'POST', headers: { Host: SIGN_IN_HOST, ...headers } }));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetExchanges();
  resetCookieWrites();
  server.use(...authHandlers);
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/screens/session', () => {
  it('makes a new wall session from the device cookie and answers paired and nothing else', async () => {
    const response = await post(await deviceCookie());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'paired' });
    const session = (await unsealSession(lastWrite(SESSION_COOKIE)!.value))!;
    expect(session).toMatchObject({ role: 'wall', services: [], sub: 'dev-screen-one', device: 'dev-screen-one' });
    expect(decodeJwt(session.backendToken).role).toBe('wall');
    expect(Number(lastWrite(SESSION_COOKIE)!.options.maxAge)).toBeLessThanOrEqual(3600);
    expect(response.headers.get('cache-control')).toBe('no-store');
  });

  it('trades for the host the screen is on, as a bearer, with an empty body', async () => {
    await post(await deviceCookie());
    expect(seenExchanges).toEqual([
      { path: '/auth/device-token', host: SIGN_IN_HOST, authorization: 'Bearer device-token-for-screen-one', body: {} },
    ]);
  });

  it('answers 404 and calls nothing for a screen with no device cookie, a changed one, or one that is not ours', async () => {
    expect((await post(null)).status).toBe(404);
    expect((await post('garbage')).status).toBe(404);
    expect(seenExchanges).toEqual([]);
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
  });

  it('tells a screen the back end no longer knows (revoked, or on another host), and makes it forget its device token', async () => {
    const response = await post(await deviceCookie('a-token-nobody-issued'));
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
    expect(lastWrite(DEVICE_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
  });

  it('keeps the device token, and makes no session, when the back end is down', async () => {
    server.use(http.post(`${BACKEND_ROOT}/auth/device-token`, () => HttpResponse.json({}, { status: 503 })));
    const response = await post(await deviceCookie());
    expect(response.status).toBe(503);
    expect(lastWrite(DEVICE_COOKIE)).toBeUndefined();
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
  });

  it('refuses a request that did not come from this site’s own page, and calls nothing', async () => {
    const response = await post(await deviceCookie(), { 'Sec-Fetch-Site': 'cross-site' });
    expect(response.status).toBe(403);
    expect(seenExchanges).toEqual([]);
  });

  it('reads no tenant from the query, the body or a header', async () => {
    const cookie = await deviceCookie();
    await POST(
      requestWithCookies(`${URL_}?tenant=trust-b`, { [DEVICE_COOKIE]: cookie }, { method: 'POST', headers: { Host: SIGN_IN_HOST, 'X-Tenant-Id': 'trust-b', 'X-Forwarded-Host': 'trust-b.example.test' }, body: '{"tenant":"trust-b"}' }),
    );
    expect(seenExchanges.at(-1)?.host).toBe(SIGN_IN_HOST);
    expect(seenExchanges.at(-1)?.body).toEqual({});
  });
});
