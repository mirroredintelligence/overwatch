// @vitest-environment node
import { decodeJwt } from 'jose';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, unsealSession } from '@/lib/auth/session';
import { DEVICE_COOKIE, deviceFrom, PAIRING_COOKIE, rememberPairing } from '@/lib/screens/cookies';
import { lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { DEVICES } from '@/test/fixtures/exchange';
import { authHandlers, resetExchanges, seenExchanges } from '@/test/msw/handlers/auth';
import { pairingBackend, screenHandlers } from '@/test/msw/handlers/screens';
import { server } from '@/test/msw/server';
import { BACKEND_ROOT, SIGN_IN_HOST } from '@/test/oidc/constants';
import { http, HttpResponse } from 'msw';
import { POST as startPairing } from '../route';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// GET /api/bff/screens/pairing/[id]: the display asks whether a lead has connected it. When the
// back end says it has, the BFF takes the device token it is given once, keeps it in a sealed cookie,
// trades it for the one-hour wall token (TEN-043) and makes the wall session. The page learns
// "paired" and nothing else: the device token and the wall token never reach browser JavaScript.

const URL_ = (id: string) => `https://${SIGN_IN_HOST}/api/bff/screens/pairing/${id}`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

async function begin() {
  resetCookieWrites();
  await startPairing(requestWithCookies(`https://${SIGN_IN_HOST}/api/bff/screens/pairing`, {}, { method: 'POST', headers: { Host: SIGN_IN_HOST } }));
  return lastWrite(PAIRING_COOKIE)!.value;
}

function poll(cookie: string | null, id = 'pairing-1', headers: Record<string, string> = {}) {
  return GET(requestWithCookies(URL_(id), cookie === null ? {} : { [PAIRING_COOKIE]: cookie }, { headers: { Host: SIGN_IN_HOST, ...headers } }), ctx(id));
}

function connect() {
  pairingBackend.connect(SIGN_IN_HOST, `Bearer ${leadToken()}`, 'key-1', { code: pairingBackend.codeOf('pairing-1'), name: 'Control room' });
}

function leadToken() {
  const claims = { sub: 'stf-1', role: 'lead', exp: Math.floor(Date.now() / 1000) + 3600 };
  const body = Buffer.from(JSON.stringify(claims)).toString('base64url');
  return `h.${body}.s`;
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  pairingBackend.reset();
  resetExchanges();
  server.use(...screenHandlers, ...authHandlers);
});
afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/screens/pairing/[id]: waiting', () => {
  it('says waiting while no lead has connected the code, sets no session, and sends the secret in the header', async () => {
    const cookie = await begin();
    resetCookieWrites();
    const response = await poll(cookie);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'waiting' });
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
    expect(pairingBackend.claims).toEqual([{ id: 'pairing-1', secret: 'screen-secret-1', host: SIGN_IN_HOST }]);
  });

  it('refuses without asking the back end when the page has no pairing cookie, or names another pairing than the cookie holds', async () => {
    const cookie = await begin();
    pairingBackend.claims.length = 0;
    expect((await poll(null)).status).toBe(404);
    expect((await poll(cookie, 'pairing-2')).status).toBe(404);
    expect((await poll(cookie, '../screens')).status).toBe(404);
    expect(pairingBackend.claims).toEqual([]);
  });

  it('is 404, and forgets the pairing, when the back end refuses the secret', async () => {
    await rememberPairing({ pairingId: 'pairing-1', screenSecret: 'wrong' });
    const forged = lastWrite(PAIRING_COOKIE)!.value;
    await begin();
    resetCookieWrites();
    const response = await poll(forged);
    expect(response.status).toBe(404);
    expect(lastWrite(PAIRING_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
  });

  it('passes a throttle on, with its wait, and keeps the pairing; an outage is 503 and keeps it too', async () => {
    const cookie = await begin();
    resetCookieWrites();
    pairingBackend.failWith = { status: 429, headers: { 'Retry-After': '600' } };
    const throttled = await poll(cookie);
    expect(throttled.status).toBe(429);
    expect(throttled.headers.get('retry-after')).toBe('600');
    pairingBackend.failWith = { status: 503 };
    expect((await poll(cookie)).status).toBe(503);
    expect(lastWrite(PAIRING_COOKIE)).toBeUndefined();
  });
});

describe('GET /api/bff/screens/pairing/[id]: expired', () => {
  it('says expired and forgets the pairing, so the page asks for a new code', async () => {
    const cookie = await begin();
    pairingBackend.expire('pairing-1');
    resetCookieWrites();
    const response = await poll(cookie);
    expect(await response.json()).toEqual({ status: 'expired' });
    expect(lastWrite(PAIRING_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
  });
});

describe('GET /api/bff/screens/pairing/[id]: paired', () => {
  async function paired() {
    const cookie = await begin();
    connect();
    resetCookieWrites();
    const response = await poll(cookie);
    return { response, cookie };
  }

  it('says paired and nothing else: no device token, no wall token, no id', async () => {
    const { response } = await paired();
    expect(response.status).toBe(200);
    expect(await response.clone().json()).toEqual({ status: 'paired' });
    const everything = JSON.stringify([await response.text(), [...response.headers.entries()]]);
    expect(everything).not.toContain('device-token-for-screen-one');
    expect(everything).not.toContain(DEVICES['device-token-for-screen-one']);
    expect(everything).not.toMatch(/eyJ|stf-/);
  });

  it('makes a wall session of the back end’s one-hour token, for the screen the token names', async () => {
    await paired();
    const write = lastWrite(SESSION_COOKIE)!;
    expect(write.options).toMatchObject({ httpOnly: true, secure: true, sameSite: 'strict', path: '/' });
    const session = (await unsealSession(write.value))!;
    expect(session).toMatchObject({ role: 'wall', services: [], sub: 'dev-screen-one', device: 'dev-screen-one' });
    expect(decodeJwt(session.backendToken)).toMatchObject({ role: 'wall', sub: 'dev-screen-one' });
    expect(Number(write.options.maxAge)).toBeGreaterThan(3500);
    expect(Number(write.options.maxAge)).toBeLessThanOrEqual(3600);
  });

  it('keeps the device token in its own sealed cookie, and not in the session', async () => {
    await paired();
    const session = (await unsealSession(lastWrite(SESSION_COOKIE)!.value))!;
    expect(JSON.stringify(session)).not.toContain('device-token-for-screen-one');
    const device = lastWrite(DEVICE_COOKIE)!;
    expect(device.value).not.toContain('device-token-for-screen-one');
    expect(await deviceFrom(requestWithCookies(URL_('x'), { [DEVICE_COOKIE]: device.value }))).toBe('device-token-for-screen-one');
  });

  it('stores the device token before it trades it, so a failed trade does not lose the one chance to collect it', async () => {
    const cookie = await begin();
    connect();
    server.use(http.post(`${BACKEND_ROOT}/auth/device-token`, () => HttpResponse.json({}, { status: 503 })));
    resetCookieWrites();
    const response = await poll(cookie);
    expect(await response.json()).toEqual({ status: 'connecting' });
    expect(lastWrite(DEVICE_COOKIE)).toBeDefined();
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
  });

  it('trades the device token for the host the display is on, as a bearer, with an empty body', async () => {
    await paired();
    expect(seenExchanges).toEqual([
      { path: '/auth/device-token', host: SIGN_IN_HOST, authorization: 'Bearer device-token-for-screen-one', body: {} },
    ]);
  });

  it('forgets the pairing once it has the token', async () => {
    await paired();
    expect(lastWrite(PAIRING_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
  });

  it('answers paired with no token, when the display asks again after it has already collected one, by trading the device cookie it holds', async () => {
    const { cookie } = await paired();
    const deviceCookie = lastWrite(DEVICE_COOKIE)!.value;
    resetCookieWrites();
    const again = await GET(
      requestWithCookies(URL_('pairing-1'), { [PAIRING_COOKIE]: cookie, [DEVICE_COOKIE]: deviceCookie }, { headers: { Host: SIGN_IN_HOST } }),
      ctx('pairing-1'),
    );
    expect(await again.json()).toEqual({ status: 'paired' });
    expect(unsealSession(lastWrite(SESSION_COOKIE)!.value)).resolves.toMatchObject({ role: 'wall' });
  });

  it('says expired, so the page starts again, when the back end says paired with no token and the display holds none', async () => {
    const { cookie } = await paired();
    resetCookieWrites();
    const again = await poll(cookie);
    expect(await again.json()).toEqual({ status: 'expired' });
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
    expect(lastWrite(PAIRING_COOKIE)).toMatchObject({ value: '' });
  });

  it('does not log the device token, the wall token or the secret', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((l) => vi.spyOn(console, l).mockImplementation(() => {}));
    const cookie = await begin();
    connect();
    await poll(cookie);
    const logged = spies.flatMap((s) => s.mock.calls).join(' ');
    for (const secret of ['device-token-for-screen-one', 'screen-secret-1', 'dev-screen-one', 'eyJ']) expect(logged).not.toContain(secret);
  });
});
