// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { standInToken, DEVICES } from '@/test/fixtures/exchange';
import { authHandlers, resetExchanges, seenExchanges } from '@/test/msw/handlers/auth';
import { pairingBackend, screenHandlers } from '@/test/msw/handlers/screens';
import { server } from '@/test/msw/server';
import { BACKEND_ROOT, SIGN_IN_HOST } from '@/test/oidc/constants';
import { claimPairing, connectScreen, exchangeDeviceToken, ScreenApiError, startPairing } from './server';

// The BFF's calls to the back end's wall screen routes (R15, DEC-224) and the device token exchange
// (TEN-043, DEC-526). The tenant is the host the browser came to and nothing else.

const NOW = new Date('2026-10-30T09:00:00Z');
const LEAD_TOKEN = standInToken({ sub: 'stf-1', role: 'lead', aud: 'diucs-api', exp: Math.floor(NOW.getTime() / 1000) + 3600 });
const ADVISOR_TOKEN = standInToken({ sub: 'stf-2', role: 'advisor', aud: 'diucs-api', exp: Math.floor(NOW.getTime() / 1000) + 3600 });

async function kindOf(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ScreenApiError) return error.kind;
    throw error;
  }
  return 'accepted';
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  pairingBackend.reset();
  resetExchanges();
  server.use(...screenHandlers, ...authHandlers);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe('startPairing', () => {
  it('asks for a code for the host the browser came to, with no token and no tenant, and returns the four fields', async () => {
    const started = await startPairing(SIGN_IN_HOST);
    expect(started).toEqual({
      pairingId: 'pairing-1',
      code: '482913',
      expiresAt: '2026-10-30T09:10:00.000Z',
      screenSecret: 'screen-secret-1',
    });
    expect(pairingBackend.starts).toEqual([{ host: SIGN_IN_HOST }]);
  });

  it('is the not-found answer for a host no tenant owns, whatever the back end says', async () => {
    expect(await kindOf(startPairing('unknown.example.test'))).toBe('not-found');
  });

  it('carries the back end’s wait on a throttle, as digits only', async () => {
    pairingBackend.failWith = { status: 429, headers: { 'Retry-After': '600' } };
    await expect(startPairing(SIGN_IN_HOST)).rejects.toMatchObject({ kind: 'throttled', retryAfter: '600' });
    pairingBackend.failWith = { status: 429, headers: { 'Retry-After': 'soon<script>' } };
    await expect(startPairing(SIGN_IN_HOST)).rejects.toMatchObject({ kind: 'throttled', retryAfter: undefined });
  });

  it.each([500, 502, 503])('is unavailable for a %i', async (status) => {
    pairingBackend.failWith = { status };
    expect(await kindOf(startPairing(SIGN_IN_HOST))).toBe('unavailable');
  });

  it('is unavailable when the back end cannot be reached, and refuses a host that is not a host name', async () => {
    server.use(http.post(`${BACKEND_ROOT}/screens/pairing`, () => HttpResponse.error()));
    expect(await kindOf(startPairing(SIGN_IN_HOST))).toBe('unavailable');
    pairingBackend.reset();
    expect(await kindOf(startPairing('a b/c'))).toBe('unavailable');
    expect(await kindOf(startPairing(null))).toBe('unavailable');
    expect(pairingBackend.starts).toEqual([]);
  });

  it.each([
    ['a code that is not six digits', { code: '48291' }],
    ['a code with a space in it', { code: '482 913' }],
    ['no pairing id', { pairingId: undefined }],
    ['a pairing id that is not a plain id', { pairingId: '../x' }],
    ['no secret', { screenSecret: undefined }],
    ['an expiry that is not a date', { expiresAt: 'soon' }],
  ])('is a bad answer when it holds %s', async (_name, change) => {
    const good = { pairingId: 'pairing-1', code: '482913', expiresAt: '2026-10-30T09:10:00Z', screenSecret: 'screen-secret-1' };
    server.use(http.post(`${BACKEND_ROOT}/screens/pairing`, () => HttpResponse.json({ ...good, ...change }, { status: 201 })));
    expect(await kindOf(startPairing(SIGN_IN_HOST))).toBe('bad-answer');
  });
});

describe('claimPairing', () => {
  it('puts the secret in the X-Screen-Secret header, never in the address, and the host as the tenant', async () => {
    const { pairingId, screenSecret } = await startPairing(SIGN_IN_HOST);
    expect(await claimPairing(SIGN_IN_HOST, pairingId, screenSecret)).toEqual({ status: 'waiting' });
    expect(pairingBackend.claims).toEqual([{ id: pairingId, secret: screenSecret, host: SIGN_IN_HOST }]);
  });

  it('gives the device token once, when a lead has connected the code', async () => {
    const { pairingId, screenSecret, code } = await startPairing(SIGN_IN_HOST);
    pairingBackend.connect(SIGN_IN_HOST, `Bearer ${LEAD_TOKEN}`, 'key-1', { code, name: 'Control room' });
    const first = await claimPairing(SIGN_IN_HOST, pairingId, screenSecret);
    expect(first).toEqual({ status: 'paired', deviceToken: 'device-token-for-screen-one' });
    // The token is not given twice: a second claim is paired with none.
    expect(await claimPairing(SIGN_IN_HOST, pairingId, screenSecret)).toEqual({ status: 'paired', deviceToken: null });
  });

  it('says expired when the ten minutes have run out', async () => {
    const { pairingId, screenSecret } = await startPairing(SIGN_IN_HOST);
    pairingBackend.expire(pairingId);
    expect(await claimPairing(SIGN_IN_HOST, pairingId, screenSecret)).toEqual({ status: 'expired' });
  });

  it('is the one not-found answer for a wrong secret and for another tenant’s pairing', async () => {
    const { pairingId, screenSecret } = await startPairing(SIGN_IN_HOST);
    expect(await kindOf(claimPairing(SIGN_IN_HOST, pairingId, 'wrong'))).toBe('not-found');
    expect(await kindOf(claimPairing('trust-b.example.test', pairingId, screenSecret))).toBe('not-found');
  });

  it.each(['', '../screens', 'a/b', 'a b', 'x'.repeat(65), 'id?x=1'])('does not call the back end for the pairing id %j', async (id) => {
    expect(await kindOf(claimPairing(SIGN_IN_HOST, id, 'secret'))).toBe('not-found');
    expect(pairingBackend.claims).toEqual([]);
  });

  it('drops every field of the answer but the status and the device token', async () => {
    server.use(
      http.get(`${BACKEND_ROOT}/screens/pairing/:id`, () =>
        HttpResponse.json({ status: 'paired', deviceToken: 'tok', tenant: 'trust-a', extra: 1 }),
      ),
    );
    expect(await claimPairing(SIGN_IN_HOST, 'pairing-1', 'secret')).toEqual({ status: 'paired', deviceToken: 'tok' });
  });

  it.each([
    ['a status it does not know', { status: 'connected' }],
    ['no status', {}],
    ['a device token that is not text', { status: 'paired', deviceToken: 7 }],
    ['an empty device token', { status: 'paired', deviceToken: '' }],
    ['a device token with a line break', { status: 'paired', deviceToken: 'a\r\nb' }],
    ['a device token on a status that is not paired', { status: 'waiting', deviceToken: 'tok' }],
  ])('is a bad answer when it holds %s', async (_name, body) => {
    server.use(http.get(`${BACKEND_ROOT}/screens/pairing/:id`, () => HttpResponse.json(body)));
    expect(await kindOf(claimPairing(SIGN_IN_HOST, 'pairing-1', 'secret'))).toBe('bad-answer');
  });

  it('is throttled for a 429 and unavailable for a 503', async () => {
    pairingBackend.failWith = { status: 429, headers: { 'Retry-After': '600' } };
    expect(await kindOf(claimPairing(SIGN_IN_HOST, 'pairing-1', 's'))).toBe('throttled');
    pairingBackend.failWith = { status: 503 };
    expect(await kindOf(claimPairing(SIGN_IN_HOST, 'pairing-1', 's'))).toBe('unavailable');
  });
});

describe('exchangeDeviceToken', () => {
  it('sends the device token as a bearer and an empty body to the host, and keeps the back end’s wall token', async () => {
    const grant = await exchangeDeviceToken(SIGN_IN_HOST, 'device-token-for-screen-one', NOW);
    expect(seenExchanges).toEqual([
      { path: '/auth/device-token', host: SIGN_IN_HOST, authorization: 'Bearer device-token-for-screen-one', body: {} },
    ]);
    expect(grant).toMatchObject({ sub: DEVICES['device-token-for-screen-one'], expiresAt: '2026-10-30T10:00:00.000Z' });
    expect(Object.keys(grant).sort()).toEqual(['expiresAt', 'sub', 'token']);
  });

  it('is the not-found answer for a screen the back end does not know, has revoked or cannot place on this host', async () => {
    expect(await kindOf(exchangeDeviceToken(SIGN_IN_HOST, 'a-token-nobody-issued', NOW))).toBe('not-found');
    expect(await kindOf(exchangeDeviceToken('unknown.example.test', 'device-token-for-screen-one', NOW))).toBe('not-found');
  });

  it('is unavailable for a 5xx or 429, and when the back end cannot be reached', async () => {
    for (const status of [429, 500, 503]) {
      server.use(http.post(`${BACKEND_ROOT}/auth/device-token`, () => HttpResponse.json({}, { status })));
      expect(await kindOf(exchangeDeviceToken(SIGN_IN_HOST, 'device-token-for-screen-one', NOW))).toBe('unavailable');
    }
    server.use(http.post(`${BACKEND_ROOT}/auth/device-token`, () => HttpResponse.error()));
    expect(await kindOf(exchangeDeviceToken(SIGN_IN_HOST, 'device-token-for-screen-one', NOW))).toBe('unavailable');
  });

  it.each([
    ['a staff role', { role: 'lead' }, { role: 'lead' }],
    ['no role', { role: undefined }, { role: 'wall' }],
    ['a token that is not three parts', { token: 'abc' }, {}],
    ['an expiry in the past', { expiresAt: '2026-10-30T08:00:00Z' }, { exp: 1 }],
    ['an expiry more than twelve hours on', { expiresAt: '2026-10-31T09:30:00Z' }, { exp: 4_000_000_000 }],
  ])('is a bad answer when it holds %s', async (_name, change, claims) => {
    const token = standInToken({ sub: 'dev-screen-one', role: 'wall', aud: 'diucs-api', exp: Math.floor(NOW.getTime() / 1000) + 3600, ...claims });
    server.use(
      http.post(`${BACKEND_ROOT}/auth/device-token`, () =>
        HttpResponse.json({ token, expiresAt: '2026-10-30T10:00:00Z', role: 'wall', ...change }),
      ),
    );
    expect(await kindOf(exchangeDeviceToken(SIGN_IN_HOST, 'device-token-for-screen-one', NOW))).toBe('bad-answer');
  });
});

describe('connectScreen', () => {
  async function connect(over: Partial<Parameters<typeof connectScreen>[2]> = {}, token = LEAD_TOKEN, key = 'key-1') {
    const started = await startPairing(SIGN_IN_HOST);
    return connectScreen(SIGN_IN_HOST, token, { code: started.code, name: 'Control room', location: null, ...over }, key);
  }

  it('sends the lead’s token, an idempotency key and the code and name, and nothing that names a tenant', async () => {
    const result = await connect({ location: 'Ward 4 corridor' });
    expect(result).toEqual({ name: 'Control room', status: 'online' });
    const sent = pairingBackend.connects.at(-1)!;
    expect(sent.authorization).toBe(`Bearer ${LEAD_TOKEN}`);
    expect(sent.idempotencyKey).toBe('key-1');
    expect(sent.body).toEqual({ code: '482913', name: 'Control room', location: 'Ward 4 corridor' });
  });

  it('leaves the location out when there is none, and never sends a board scope the page did not offer', async () => {
    await connect();
    expect(pairingBackend.connects.at(-1)!.body).toEqual({ code: '482913', name: 'Control room' });
  });

  it('is the not-found answer for a code that is wrong, expired or used, and for a token that is not a lead’s', async () => {
    expect(await kindOf(connect({ code: '000000' }))).toBe('not-found');
    expect(await kindOf(connect({}, ADVISOR_TOKEN))).toBe('not-found');
  });

  it('is invalid for a 400 or 422, throttled for a 429, unauthorised for a 401', async () => {
    for (const [status, kind] of [[400, 'invalid'], [422, 'invalid'], [429, 'throttled'], [401, 'unauthorised'], [403, 'unauthorised'], [503, 'unavailable']] as const) {
      server.use(http.post(`${BACKEND_ROOT}/screens`, () => HttpResponse.json({}, { status })));
      expect(await kindOf(connect())).toBe(kind);
    }
  });

  it('is a bad answer when a 201 does not say online', async () => {
    server.use(http.post(`${BACKEND_ROOT}/screens`, () => HttpResponse.json({ name: 'x', status: 'offline' }, { status: 201 })));
    expect(await kindOf(connect())).toBe('bad-answer');
  });

  it('shows no token, secret or code in what it throws', async () => {
    try {
      await connect({}, ADVISOR_TOKEN);
    } catch (error) {
      expect(String(error)).not.toContain(ADVISOR_TOKEN);
      expect(String(error)).not.toContain('482913');
    }
  });
});
