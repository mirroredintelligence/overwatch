// @vitest-environment node
import { http } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { A, BACKEND, DEVICE, exchangeBody, exchangeHandler, iso, PERSON, PIN_SESSION, reporterToken, type SeenExchange } from '@/test/fixtures/reporter';
import { server } from '@/test/msw/server';
import { exchangeSessionToken, MAX_TOKEN_MS, type ExchangeInput } from './exchange';

// A live PIN session is exchanged for a 30-minute reporter token (W7B A2, DEC-792). The BFF holds no
// signing secret, names no tenant and decides no role: it sends the PIN session id and the host, and
// believes the answer only when it is a reporter token for the tenant, the phone and (on a renewal)
// the person the session was made for. Every claim that is not what was expected is `invalid`.

const NOW = new Date('2026-10-30T09:00:00Z');
const seen: SeenExchange[] = [];
let reply: Parameters<typeof exchangeHandler>[1];

const INPUT: ExchangeInput = { pinSession: PIN_SESSION, host: A.host, tenantId: A.id, device: DEVICE };

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  seen.length = 0;
  reply = () => ({ body: exchangeBody({}, {}, NOW) });
  server.use(exchangeHandler(seen, () => reply()));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

const answer = (body: unknown, status = 200) => {
  reply = () => ({ status, body });
};

describe('exchangeSessionToken: what is sent', () => {
  it('posts the PIN session id and nothing else, addressed to the host, with no bearer', async () => {
    await exchangeSessionToken(INPUT, NOW);
    expect(seen).toEqual([{ host: A.host, authorization: null, body: { sessionId: PIN_SESSION } }]);
  });

  it('names no tenant, role, person or service in the body, whatever the input holds', async () => {
    await exchangeSessionToken({ ...INPUT, sub: PERSON }, NOW);
    expect(Object.keys(seen[0]?.body as object)).toEqual(['sessionId']);
  });
});

describe('exchangeSessionToken: what is believed', () => {
  it('gives the token, the person, the services and the earlier of the answer’s expiry and the token’s', async () => {
    const issued = await exchangeSessionToken(INPUT, NOW);
    expect(issued.kind).toBe('issued');
    if (issued.kind !== 'issued') return;
    expect(issued.sub).toBe(PERSON);
    expect(issued.services).toEqual(['s1']);
    expect(issued.tokenExpiresAt).toBe(iso(new Date(NOW.getTime() + 30 * 60_000)));
    expect(issued.token.split('.')).toHaveLength(3);
  });

  it('takes the answer’s expiry when it is earlier than the token’s', async () => {
    answer(exchangeBody({ expiresAt: iso(new Date(NOW.getTime() + 10 * 60_000)) }, {}, NOW));
    const issued = await exchangeSessionToken(INPUT, NOW);
    expect(issued).toMatchObject({ kind: 'issued', tokenExpiresAt: iso(new Date(NOW.getTime() + 10 * 60_000)) });
  });

  it('takes the token’s expiry when it is earlier than the answer’s', async () => {
    answer(exchangeBody({}, { exp: Math.floor(NOW.getTime() / 1000) + 600 }, NOW));
    const issued = await exchangeSessionToken(INPUT, NOW);
    expect(issued).toMatchObject({ kind: 'issued', tokenExpiresAt: iso(new Date(NOW.getTime() + 10 * 60_000)) });
  });

  it('accepts the same person on a renewal', async () => {
    expect((await exchangeSessionToken({ ...INPUT, sub: PERSON }, NOW)).kind).toBe('issued');
  });

  it.each([
    ['another person (renewal)', { ...INPUT, sub: 'prac-other-person-0123456789abcdef0' }, {}],
    ['another tenant', INPUT, { tenant: 'trust-b' }],
    ['another phone', INPUT, { device: 'E'.repeat(22) }],
    ['no phone', INPUT, { device: undefined }],
    ['a role that is not reporter', INPUT, { role: 'lead' }],
    ['another audience', INPUT, { aud: 'diucs-operator' }],
    ['an expired token', INPUT, { exp: Math.floor(NOW.getTime() / 1000) - 1 }],
    ['a token that lasts longer than an hour', INPUT, { exp: Math.floor(NOW.getTime() / 1000) + 61 * 60 }],
    ['a network id as its tenant', INPUT, { tenant: 'net-sample' }],
    ['no subject', INPUT, { sub: '' }],
  ] as const)('does not believe %s: invalid', async (_name, input, claims) => {
    answer(exchangeBody({}, claims as never, NOW));
    expect(await exchangeSessionToken(input, NOW)).toEqual({ kind: 'invalid' });
  });

  it('does not believe a token for the tenant of the host when the session was made for another', async () => {
    answer(exchangeBody({}, { tenant: 'trust-b' }, NOW));
    expect(await exchangeSessionToken({ ...INPUT, tenantId: 'trust-b', device: DEVICE }, NOW)).toMatchObject({ kind: 'issued' });
    expect(await exchangeSessionToken(INPUT, NOW)).toEqual({ kind: 'invalid' });
  });

  it.each([
    ['an answer role that is not reporter', exchangeBody({ role: 'lead' }, {}, NOW)],
    ['an answer role that is missing', exchangeBody({ role: undefined }, {}, NOW)],
    ['no token', exchangeBody({ token: undefined }, {}, NOW)],
    ['a token that is not text', exchangeBody({ token: 7 }, {}, NOW)],
    ['a token that is not a token', exchangeBody({ token: 'not-a-token' }, {}, NOW)],
    ['an expiry that is not a date', exchangeBody({ expiresAt: 'tomorrow' }, {}, NOW)],
    ['no expiry', exchangeBody({ expiresAt: undefined }, {}, NOW)],
    ['an expiry already past', exchangeBody({ expiresAt: iso(new Date(NOW.getTime() - 1000)) }, {}, NOW)],
    ['an expiry more than an hour away', exchangeBody({ expiresAt: iso(new Date(NOW.getTime() + MAX_TOKEN_MS + 60_000)) }, {}, NOW)],
    ['an array', []],
    ['text', 'ok'],
    ['null', null],
  ])('does not believe %s: invalid', async (_name, body) => {
    answer(body);
    expect(await exchangeSessionToken(INPUT, NOW)).toEqual({ kind: 'invalid' });
  });

  it('does not believe a 200 whose body is not JSON: unavailable', async () => {
    server.use(http.post(`${BACKEND}/identity/session-token`, () => new Response('<html>', { status: 200 })));
    expect(await exchangeSessionToken(INPUT, NOW)).toEqual({ kind: 'unavailable' });
  });

  it('puts neither the token nor the session id in what it returns for a refusal', async () => {
    answer({ resourceType: 'OperationOutcome', issue: [{ code: 'not-found' }] }, 404);
    const result = await exchangeSessionToken(INPUT, NOW);
    expect(JSON.stringify(result)).not.toContain(PIN_SESSION);
  });
});

describe('exchangeSessionToken: what the back end can say', () => {
  it.each([400, 401, 403, 404, 410, 422])('a %i is a refusal: the session has ended', async (status) => {
    answer({ resourceType: 'OperationOutcome' }, status);
    expect(await exchangeSessionToken(INPUT, NOW)).toEqual({ kind: 'refused' });
  });

  it.each([429, 500, 502, 503, 504])('a %i is unavailable, not a refusal', async (status) => {
    answer({}, status);
    expect(await exchangeSessionToken(INPUT, NOW)).toEqual({ kind: 'unavailable' });
  });

  it('a back end that cannot be reached is unavailable', async () => {
    reply = () => 'network-error';
    expect(await exchangeSessionToken(INPUT, NOW)).toEqual({ kind: 'unavailable' });
  });

  it('a host that is not a host name is unavailable, and nothing is sent', async () => {
    expect(await exchangeSessionToken({ ...INPUT, host: 'not a host' }, NOW)).toEqual({ kind: 'unavailable' });
    expect(seen).toHaveLength(0);
  });

  it('an address of the back end that is not set is a fault that names the variable, not an answer', async () => {
    vi.stubEnv('DIUCS_FHIR_BASE_URL', '');
    await expect(exchangeSessionToken(INPUT, NOW)).rejects.toThrow(/DIUCS_FHIR_BASE_URL/);
  });

  it('refuses a PIN session id that cannot be one without calling the back end', async () => {
    for (const bad of ['', 'x'.repeat(129), 'has space', 'a/b', 'a\nb']) {
      expect(await exchangeSessionToken({ ...INPUT, pinSession: bad }, NOW)).toEqual({ kind: 'refused' });
    }
    expect(seen).toHaveLength(0);
  });
});

// A token the stand-in signs is read by the same function the sign-in uses; keep the helper honest.
describe('the sample token', () => {
  it('is a reporter token for tenant A and the sample phone', () => {
    const [, body] = reporterToken({}, NOW).split('.');
    expect(JSON.parse(Buffer.from(body ?? '', 'base64url').toString('utf8'))).toMatchObject({ role: 'reporter', tenant: A.id, device: DEVICE, aud: 'diucs-api' });
  });
});
