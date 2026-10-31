// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { standInToken } from '@/test/fixtures/exchange';
import { server } from '@/test/msw/server';
import { BACKEND_ROOT } from '@/test/oidc/constants';
import { SignInRefused } from '@/lib/auth/oidc';
import { exchangeOperatorToken } from './exchange';

// The operator's sign-in, last step (TEN-083, DEC-1000, DEC-1005): the verified ID token of the OPERATOR
// directory goes to `POST /auth/operator-token`, which answers `{token, expiresAt, role}` with a token of
// the audience `diucs-ops` that names no tenant. Anything else is not an operator's token and is not kept.

const NOW = new Date('2026-10-30T09:00:00Z');
const SECONDS = Math.floor(NOW.getTime() / 1000);
const HOST = 'console.example.test';
const ID_TOKEN = standInToken({ tid: '44444444-4444-4444-8444-444444444444', oid: 'aaaaaaaa-0000-4000-8000-000000000009', roles: ['DIUCS.PlatformOperator'] });

type Seen = { host: string | null; authorization: string | null; body: unknown };
const seen: Seen[] = [];

function answer(over: Record<string, unknown> = {}, claims: Record<string, unknown> = {}, status = 200) {
  const token = standInToken({ sub: 'ops-0123456789abcdef0123456789abcdef', role: 'platform-operator', aud: 'diucs-ops', iat: SECONDS, exp: SECONDS + 3600, ...claims });
  server.use(
    http.post(`${BACKEND_ROOT}/auth/operator-token`, async ({ request }) => {
      seen.push({ host: request.headers.get('host'), authorization: request.headers.get('authorization'), body: await request.json().catch(() => undefined) });
      return HttpResponse.json({ token, expiresAt: '2026-10-30T10:00:00Z', role: 'platform-operator', ...over }, { status });
    }),
  );
  return token;
}

async function reasonOf(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof SignInRefused) return error.reason;
    throw error;
  }
  return 'accepted';
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  seen.length = 0;
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe('exchangeOperatorToken', () => {
  it('posts the ID token and nothing else, with no bearer', async () => {
    answer();
    await exchangeOperatorToken(ID_TOKEN, HOST, NOW);
    expect(seen).toEqual([{ host: HOST, authorization: null, body: { idToken: ID_TOKEN } }]);
  });

  it('returns the token, its end, the role the back end chose and the account reference it derived', async () => {
    const token = answer();
    expect(await exchangeOperatorToken(ID_TOKEN, HOST, NOW)).toEqual({
      kind: 'issued',
      grant: { token, expiresAt: '2026-10-30T10:00:00.000Z', role: 'platform-operator', sub: 'ops-0123456789abcdef0123456789abcdef' },
    });
  });

  it('accepts the support role', async () => {
    answer({ role: 'support' }, { role: 'support' });
    expect(await exchangeOperatorToken(ID_TOKEN, HOST, NOW)).toMatchObject({ kind: 'issued', grant: { role: 'support' } });
  });

  it('is the one refusal for a 403 whatever the body says', async () => {
    server.use(http.post(`${BACKEND_ROOT}/auth/operator-token`, () => HttpResponse.text('not in the operator directory', { status: 403 })));
    expect(await exchangeOperatorToken(ID_TOKEN, HOST, NOW)).toEqual({ kind: 'refused' });
  });

  it.each(['advisor', 'lead', 'tenant-admin', 'network-admin', 'wall', 'root', '', 7, null])(
    'is a bad answer when the role is %j: a tenant role is never an operator’s',
    async (role) => {
      answer({ role }, { role: typeof role === 'string' ? role : 'platform-operator' });
      expect(await reasonOf(exchangeOperatorToken(ID_TOKEN, HOST, NOW))).toBe('exchange-answer');
    },
  );

  it.each([
    ['a token for the staff audience', { aud: 'diucs-api' }],
    ['a token with no audience', { aud: undefined }],
    ['a token that names a tenant', { tenant: 'trust-a' }],
    ['a token that carries an epoch', { epoch: 1 }],
    ['a token that carries services', { services: [] }],
    ['a token that carries a device', { device: 'dev-1' }],
    ['a token with no subject', { sub: undefined }],
    ['a token whose role is not the answer’s', { role: 'support' }],
    ['a token already expired', { exp: SECONDS - 1 }],
    ['a token that lasts more than twelve hours', { exp: SECONDS + 13 * 3600 }],
  ])('is a bad answer for %s', async (_name, claims) => {
    server.use(
      http.post(`${BACKEND_ROOT}/auth/operator-token`, () =>
        HttpResponse.json({
          token: standInToken({ sub: 'ops-0123456789abcdef0123456789abcdef', role: 'platform-operator', aud: 'diucs-ops', iat: SECONDS, exp: SECONDS + 3600, ...claims }),
          expiresAt: '2026-10-30T10:00:00Z',
          role: 'platform-operator',
        }),
      ),
    );
    expect(await reasonOf(exchangeOperatorToken(ID_TOKEN, HOST, NOW))).toBe('exchange-answer');
  });

  it('ends the session no later than the token', async () => {
    answer({ expiresAt: '2026-10-30T11:00:00Z' }, { exp: SECONDS + 1800 });
    expect(await exchangeOperatorToken(ID_TOKEN, HOST, NOW)).toMatchObject({ grant: { expiresAt: '2026-10-30T09:30:00.000Z' } });
  });

  it.each([400, 401, 404, 429, 500, 503])('is a failed sign-in, not a refusal of the person, for a %i', async (status) => {
    server.use(http.post(`${BACKEND_ROOT}/auth/operator-token`, () => HttpResponse.json({}, { status })));
    expect(await reasonOf(exchangeOperatorToken(ID_TOKEN, HOST, NOW))).toBe('exchange-failed');
  });

  it.each([null, '', 'a b'])('does not call the back end for the host %j', async (host) => {
    answer();
    expect(await reasonOf(exchangeOperatorToken(ID_TOKEN, host, NOW))).toBe('exchange-failed');
    expect(seen).toHaveLength(0);
  });

  it.each(['', 'x'.repeat(8193)])('does not call the back end for an ID token of %j characters', async (value) => {
    answer();
    expect(await reasonOf(exchangeOperatorToken(value, HOST, NOW))).toBe('bad-token');
    expect(seen).toHaveLength(0);
  });
});
