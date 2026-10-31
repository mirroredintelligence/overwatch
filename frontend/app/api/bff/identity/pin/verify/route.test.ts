// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, unsealSession } from '@/lib/auth/session';
import { claimsOf } from '@/test/backendToken';
import { A, BACKEND, DEVICE, exchangeBody, exchangeHandler, iso, PERSON, PIN_SESSION, SIGNED_IN, type SeenExchange } from '@/test/fixtures/reporter';
import { cookieWrites, cookiesMock, lastWrite, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { requestPreSession } from '@/test/requests';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The reporter's PIN sign-in (W34, W35, W8E). The back end answers the PIN session; the BFF exchanges
// it for a 30-minute reporter token (DEC-792) and seals THAT as the bearer, with the PIN session kept
// beside it for the renewal. The session is for the tenant the back end answers with and the host the
// phone came to; an answer, or a token, that is not what was asked for signs nobody in. Neither the
// PIN session id nor the token ever reaches the browser.

const NOW = new Date('2026-10-30T09:00:00Z');
const PIN_VERIFY = `${BACKEND}/identity/pin/verify`;
const seen: SeenExchange[] = [];
let exchangeReply: Parameters<typeof exchangeHandler>[1];

function pinAnswer(body: unknown, status = 200) {
  server.use(http.post(PIN_VERIFY, () => HttpResponse.json(body as Record<string, unknown>, { status })));
}
const call = async (options: Parameters<typeof requestPreSession>[0] = {}) =>
  POST(await requestPreSession({ host: A.host, path: '/api/bff/identity/pin/verify', body: '{"pin":"123456"}', ...options }), { params: Promise.resolve({}) });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
  seen.length = 0;
  exchangeReply = () => ({ body: exchangeBody({}, { services: ['s1', 's2'] }, new Date()) });
  server.use(exchangeHandler(seen, () => exchangeReply()));
  pinAnswer(SIGNED_IN);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

const sealed = async () => unsealSession(lastWrite(SESSION_COOKIE)?.value ?? '', NOW);

describe('POST /api/bff/identity/pin/verify: a right PIN', () => {
  it('exchanges the PIN session for a token and seals the token as the bearer, with the PIN session beside it', async () => {
    const response = await call();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
    const session = await sealed();
    expect(session).toMatchObject({
      role: 'reporter',
      tenantId: A.id,
      host: A.host,
      sub: PERSON,
      device: DEVICE,
      pinSession: PIN_SESSION,
      services: ['s1', 's2'],
      tokenExpiresAt: iso(new Date(NOW.getTime() + 30 * 60_000)),
    });
    expect(session?.backendToken).not.toBe(PIN_SESSION);
    expect(claimsOf(session?.backendToken ?? '')).toMatchObject({ role: 'reporter', tenant: A.id, sub: PERSON });
  });

  it('seals the cookie as HTTP-only and same-site strict, ending eight hours after sign-in', async () => {
    await call();
    const write = lastWrite(SESSION_COOKIE);
    expect(write?.options).toMatchObject({ httpOnly: true, sameSite: 'strict', secure: true, maxAge: 8 * 3600 });
    expect((await sealed())?.expiresAt).toBe(new Date(NOW.getTime() + 8 * 3_600_000).toISOString());
  });

  it('asks for the exchange with the PIN session id, addressed to the host the phone came to', async () => {
    await call();
    expect(seen).toEqual([{ host: A.host, authorization: null, body: { sessionId: PIN_SESSION } }]);
  });

  it('puts neither the PIN session id, the token nor the tenant in the answer the browser reads', async () => {
    const response = await call();
    const text = await response.text();
    expect(text).not.toContain(PIN_SESSION);
    expect(text).not.toContain(A.id);
    expect(text).not.toContain(PERSON);
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it('uses the services the token names, not the PIN answer’s list', async () => {
    pinAnswer({ ...SIGNED_IN, services: ['s9'] });
    await call();
    expect((await sealed())?.services).toEqual(['s1', 's2']);
  });
});

describe('POST /api/bff/identity/pin/verify: a sign-in that is not believed', () => {
  it.each([
    ['no tenant', undefined],
    ['a network id', 'net-sample'],
    ['a value that is not an id', 'Not A Tenant!'],
    ['a number', 7],
  ])('signs nobody in, and does not even ask for a token, when the back end answers %s', async (_name, tenant) => {
    pinAnswer({ ...SIGNED_IN, tenant });
    const response = await call();
    expect(response.status).toBe(503);
    expect(seen).toHaveLength(0);
    expect(cookieWrites.some((w) => w.name === SESSION_COOKIE)).toBe(false);
  });

  it.each([
    ['another tenant than the sign-in named', { tenant: 'trust-b' }],
    ['another phone than the one that signed in', { device: 'E'.repeat(22) }],
    ['a role that is not reporter', { role: 'lead' }],
    ['no phone', { device: undefined }],
    ['an expired token', { exp: Math.floor(NOW.getTime() / 1000) - 1 }],
  ])('signs nobody in when the token is for %s', async (_name, claims) => {
    exchangeReply = () => ({ body: exchangeBody({}, claims as never, new Date()) });
    const response = await call();
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ code: 'unavailable' });
    expect(cookieWrites.some((w) => w.name === SESSION_COOKIE)).toBe(false);
  });

  it.each([
    ['a refusal', { status: 404, body: {} }],
    ['a failure', { status: 500, body: {} }],
    ['a body that is not an answer', { status: 200, body: { nothing: true } }],
  ] as const)('signs nobody in when the exchange gives %s', async (_name, answer) => {
    exchangeReply = () => answer;
    expect((await call()).status).toBe(503);
    expect(cookieWrites.some((w) => w.name === SESSION_COOKIE)).toBe(false);
  });

  it('signs nobody in when the back end cannot be reached for the exchange', async () => {
    exchangeReply = () => 'network-error';
    expect((await call()).status).toBe(503);
    expect(cookieWrites.some((w) => w.name === SESSION_COOKIE)).toBe(false);
  });
});

describe('POST /api/bff/identity/pin/verify: every other answer asks for no token', () => {
  it('answers a wrong PIN with the tries left, a locked one as locked, and one that needs a text code as reverify', async () => {
    pinAnswer({ triesLeft: 3 }, 403);
    expect(await (await call()).json()).toEqual({ ok: false, triesLeft: 3 });
    pinAnswer({}, 423);
    expect(await (await call()).json()).toEqual({ locked: true });
    pinAnswer({ needsTextCode: true }, 403);
    expect(await (await call()).json()).toEqual({ reverify: true });
    expect(seen).toHaveLength(0);
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
  });

  it('answers 503 for an answer it cannot read', async () => {
    pinAnswer({ unexpected: true }, 500);
    expect((await call()).status).toBe(503);
    expect(seen).toHaveLength(0);
  });
});

describe('POST /api/bff/identity/pin/verify: what the request may say', () => {
  it('takes no tenant from the request: a body that names one is not sent on', async () => {
    let sent: unknown;
    server.use(
      http.post(PIN_VERIFY, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(SIGNED_IN);
      }),
    );
    await call({ body: '{"pin":"123456","tenant":"trust-b"}' });
    expect(sent).toEqual({ deviceId: DEVICE, pin: '123456' });
  });

  it('refuses a write with no CSRF token of this phone, before the back end is called', async () => {
    let called = false;
    server.use(http.post(PIN_VERIFY, () => ((called = true), HttpResponse.json(SIGNED_IN))));
    expect((await call({ csrf: false })).status).toBe(403);
    expect(called).toBe(false);
    expect(seen).toHaveLength(0);
  });

  it('refuses a PIN that is not six digits, before the back end is called', async () => {
    for (const body of ['{"pin":"12345"}', '{"pin":"1234567"}', '{"pin":"12345a"}', '{"pin":123456}', '{}', 'not json']) {
      expect((await call({ body })).status, body).toBe(400);
    }
    expect(seen).toHaveLength(0);
  });
});
