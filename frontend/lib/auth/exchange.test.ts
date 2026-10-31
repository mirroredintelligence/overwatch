// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { standInToken } from '@/test/fixtures/exchange';
import { authHandlers, resetExchanges, seenExchanges } from '@/test/msw/handlers/auth';
import { BACKEND_ROOT, DIRECTORY_A, DIRECTORY_B, OID_ADVISOR, SIGN_IN_HOST } from '@/test/oidc/constants';
import { server } from '@/test/msw/server';
import { exchangeStaffToken } from './exchange';
import { SignInRefused } from './oidc';

// The BFF hands the verified ID token to the back end, which answers with the tenant-bound token it
// signed itself (TEN-043, DEC-522 to DEC-526). The front end holds no signing secret, decides no
// role and names no tenant: it sends the host the browser came to and the one credential.

const NOW = new Date('2026-10-30T09:00:00Z');
const SECONDS = Math.floor(NOW.getTime() / 1000);

function idToken(claims: Record<string, unknown>): string {
  return standInToken({ tid: DIRECTORY_A, oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], ...claims });
}

function answer(over: Record<string, unknown> = {}, tokenClaims: Record<string, unknown> = {}, status = 200) {
  const token = standInToken({ sub: 'stf-0123456789abcdef0123456789abcdef', role: 'lead', aud: 'diucs-api', iat: SECONDS, exp: SECONDS + 8 * 3600, ...tokenClaims });
  server.use(
    http.post(`${BACKEND_ROOT}/auth/token`, () =>
      HttpResponse.json({ token, expiresAt: '2026-10-30T17:00:00Z', role: 'lead', ...over }, { status }),
    ),
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
  // The stand-in back end issues tokens from the clock: hold it at NOW, as the code under test is given.
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetExchanges();
  server.use(...authHandlers);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe('exchangeStaffToken: what is sent', () => {
  it('posts the ID token and nothing else to /auth/token, addressed to the host the person came to', async () => {
    const token = idToken({});
    await exchangeStaffToken(token, SIGN_IN_HOST, NOW);
    expect(seenExchanges).toEqual([{ path: '/auth/token', host: SIGN_IN_HOST, authorization: null, body: { idToken: token } }]);
  });

  it('sends the host it is given and no other, so the tenant is the one the browser was addressed to', async () => {
    await exchangeStaffToken(idToken({ tid: DIRECTORY_B }), 'trust-b.example.test', NOW);
    expect(seenExchanges.at(-1)?.host).toBe('trust-b.example.test');
  });

  it.each([null, '', 'tenant.example.test/evil', 'a b', 'host\r\nX-Tenant: other'])(
    'does not call the back end for the host %j',
    async (host) => {
      expect(await reasonOf(exchangeStaffToken(idToken({}), host, NOW))).toBe('exchange-failed');
      expect(seenExchanges).toHaveLength(0);
    },
  );

  it.each(['', 'x'.repeat(8193)])('does not call the back end for an ID token of %j characters', async (value) => {
    expect(await reasonOf(exchangeStaffToken(value, SIGN_IN_HOST, NOW))).toBe('bad-token');
    expect(seenExchanges).toHaveLength(0);
  });
});

describe('exchangeStaffToken: what is made of the answer', () => {
  it('returns the token, its expiry, the role the back end chose and the subject the back end derived', async () => {
    const token = answer();
    const result = await exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW);
    expect(result).toEqual({
      kind: 'issued',
      grant: { token, expiresAt: '2026-10-30T17:00:00.000Z', role: 'lead', sub: 'stf-0123456789abcdef0123456789abcdef' },
    });
  });

  it('takes the role from the back end, not from anything in the ID token', async () => {
    const result = await exchangeStaffToken(idToken({ roles: ['DIUCS.Lead'] }), SIGN_IN_HOST, NOW);
    expect(result).toMatchObject({ kind: 'issued', grant: { role: 'lead' } });
    answer({ role: 'advisor' }, { role: 'advisor' });
    expect(await exchangeStaffToken(idToken({ roles: ['DIUCS.Lead'] }), SIGN_IN_HOST, NOW)).toMatchObject({
      grant: { role: 'advisor' },
    });
  });

  it('never keeps the Entra object id, a tenant or an epoch: the subject is the back end’s own', async () => {
    const result = await exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW);
    expect(Object.keys((result as { grant: object }).grant).sort()).toEqual(['expiresAt', 'role', 'sub', 'token']);
    expect(JSON.stringify(result)).not.toContain(OID_ADVISOR);
    answer({ tenant: 'trust-a', epoch: 4, subject: 'x' });
    const again = await exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW);
    expect(Object.keys((again as { grant: object }).grant).sort()).toEqual(['expiresAt', 'role', 'sub', 'token']);
  });

  it.each(['advisor', 'clinical', 'lead', 'owner', 'exec', 'audit', 'tenant-admin'])('accepts the staff role %s', async (role) => {
    answer({ role }, { role });
    expect(await exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW)).toMatchObject({ kind: 'issued', grant: { role } });
  });

  it.each(['network-admin'])('gives no session to %s: no page of this front end is for it yet', async (role) => {
    answer({ role }, { role });
    expect(await exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW)).toEqual({ kind: 'refused' });
  });

  it.each(['wall', 'reporter', 'anonymous-link', 'support', 'platform-operator', 'root', '', 7, null])(
    'is a bad answer when the role is %j: the staff exchange never gives it',
    async (role) => {
      answer({ role }, { role: typeof role === 'string' ? role : 'lead' });
      expect(await reasonOf(exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW))).toBe('exchange-answer');
    },
  );

  it('ends the session no later than the token does, even if the answer says later', async () => {
    answer({ expiresAt: '2026-10-30T17:00:00Z' }, { exp: SECONDS + 3600 });
    const result = await exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW);
    expect(result).toMatchObject({ grant: { expiresAt: '2026-10-30T10:00:00.000Z' } });
  });

  it.each([
    ['a token that is not three parts', { token: 'not-a-token' }, {}],
    ['a token that is not text', { token: 7 }, {}],
    ['no token', { token: undefined }, {}],
    ['a token of more than 4096 characters', { token: `${'a'.repeat(4100)}.b.c` }, {}],
    ['a token with no subject', {}, { sub: undefined }],
    ['a token with an empty subject', {}, { sub: '' }],
    ['a token with no expiry', {}, { exp: undefined }],
    ['an expiry that is not a date', { expiresAt: 'tomorrow' }, {}],
    ['an expiry that is not text', { expiresAt: 1793350800 }, {}],
    ['an expiry already past', { expiresAt: '2026-10-30T08:59:59Z' }, { exp: SECONDS - 1 }],
    ['an expiry more than twelve hours on', { expiresAt: '2026-10-31T09:30:00Z' }, { exp: SECONDS + 24 * 3600 }],
  ])('is a bad answer when it holds %s', async (_name, over, tokenClaims) => {
    const claims = { sub: 'stf-0123456789abcdef0123456789abcdef', role: 'lead', aud: 'diucs-api', iat: SECONDS, exp: SECONDS + 8 * 3600, ...tokenClaims };
    const token = standInToken(claims);
    server.use(
      http.post(`${BACKEND_ROOT}/auth/token`, () =>
        HttpResponse.json({ token, expiresAt: '2026-10-30T17:00:00Z', role: 'lead', ...over }),
      ),
    );
    expect(await reasonOf(exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW))).toBe('exchange-answer');
  });

  it('is a bad answer when the body is not an object, or is not JSON', async () => {
    for (const body of [[], 'text', null, 7]) {
      server.use(http.post(`${BACKEND_ROOT}/auth/token`, () => HttpResponse.json(body as never)));
      expect(await reasonOf(exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW))).toBe('exchange-answer');
    }
    server.use(http.post(`${BACKEND_ROOT}/auth/token`, () => new HttpResponse('<html>', { status: 200 })));
    expect(await reasonOf(exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW))).toBe('exchange-answer');
  });
});

describe('exchangeStaffToken: what the back end refuses', () => {
  it('is the one refusal for a person the host’s tenant has not given access to', async () => {
    // A member of directory B on the host that has bound directory A only.
    expect(await exchangeStaffToken(idToken({ tid: DIRECTORY_B }), SIGN_IN_HOST, NOW)).toEqual({ kind: 'refused' });
    // A person with no app role the tenant maps.
    expect(await exchangeStaffToken(idToken({ roles: [] }), SIGN_IN_HOST, NOW)).toEqual({ kind: 'refused' });
  });

  it('says nothing about why: a 403 of any body is the same refusal', async () => {
    server.use(http.post(`${BACKEND_ROOT}/auth/token`, () => HttpResponse.text('directory 1111 is not bound to tenant trust-a', { status: 403 })));
    const result = await exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW);
    expect(result).toEqual({ kind: 'refused' });
  });

  it.each([400, 404, 429, 500, 502, 503, 401, 418])('is a failed sign-in for a %i: not a refusal of the person', async (status) => {
    server.use(http.post(`${BACKEND_ROOT}/auth/token`, () => HttpResponse.json({}, { status })));
    expect(await reasonOf(exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW))).toBe('exchange-failed');
  });

  it('is a failed sign-in when the back end cannot be reached or the address is not set', async () => {
    server.use(http.post(`${BACKEND_ROOT}/auth/token`, () => HttpResponse.error()));
    expect(await reasonOf(exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW))).toBe('exchange-failed');
    vi.stubEnv('DIUCS_FHIR_BASE_URL', '');
    await expect(exchangeStaffToken(idToken({}), SIGN_IN_HOST, NOW)).rejects.toThrow('DIUCS_FHIR_BASE_URL');
  });

  it('puts neither the ID token, the answer’s token nor the subject in anything it throws', async () => {
    const token = idToken({});
    const issued = answer({ role: 'root' }, {});
    try {
      await exchangeStaffToken(token, SIGN_IN_HOST, NOW);
    } catch (error) {
      expect(String(error)).not.toContain(token);
      expect(String(error)).not.toContain(issued);
      expect(String(error)).not.toContain('stf-');
    }
  });
});
