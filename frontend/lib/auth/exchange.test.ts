// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { claimsOf, fakeBackendToken } from '@/test/backendToken';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { EXCHANGE_URL, resetExchanges, seenExchanges } from '@/test/msw/handlers/auth';
import { server } from '@/test/msw/server';
import { DIRECTORY_A, DIRECTORY_B, OID_ADVISOR } from '@/test/oidc/constants';
import { TENANTS } from '@/test/tenants';
import { ExchangeFailed, exchangeStaffToken } from './exchange';

// An identity token as the sign-in hands it on: the stand-in back end reads its claims only.
function identity(overrides: Record<string, unknown> = {}): string {
  const part = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
  return `${part({ alg: 'RS256' })}.${part({ tid: DIRECTORY_A, oid: OID_ADVISOR, roles: ['DIUCS.Advisor'], ...overrides })}.signature`;
}

const NOW = new Date();
const inAnHour = () => Math.floor(Date.now() / 1000) + 3600;
const iso = (seconds: number) => new Date(seconds * 1000).toISOString().replace('.000Z', 'Z');

function answer(body: unknown, init: { status?: number } = {}) {
  server.use(http.post(EXCHANGE_URL, () => HttpResponse.json(body as Record<string, unknown>, { status: init.status ?? 200 })));
}

function issued(overrides: { claims?: Record<string, unknown>; role?: string; expiresAt?: string } = {}) {
  const exp = inAnHour();
  const claims = { role: 'advisor', tenant: TENANTS.A.id, exp, ...overrides.claims };
  return { token: fakeBackendToken(claims), expiresAt: overrides.expiresAt ?? iso(exp), role: overrides.role ?? 'advisor' };
}

async function failure(call: Promise<unknown>): Promise<ExchangeFailed> {
  const error = await call.then(
    () => null,
    (e: unknown) => e,
  );
  expect(error).toBeInstanceOf(ExchangeFailed);
  return error as ExchangeFailed;
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetExchanges();
});

describe('exchangeStaffToken: what is sent', () => {
  it('posts the identity token alone, to the back end, addressed to the tenant host', async () => {
    const id = identity();
    await exchangeStaffToken(id, TENANTS.A.host, NOW);
    expect(seenExchanges).toHaveLength(1);
    expect(seenExchanges[0]).toEqual({ host: TENANTS.A.host, body: { idToken: id }, authorization: null });
  });

  it('keeps the port when the host has one (development)', async () => {
    server.use(http.post(EXCHANGE_URL, ({ request }) => {
      seenExchanges.push({ host: request.headers.get('host'), body: null, authorization: null });
      return HttpResponse.json(issued());
    }));
    await exchangeStaffToken(identity(), 'localhost:20000', NOW);
    expect(seenExchanges[0]?.host).toBe('localhost:20000');
  });

  it('sends no tenant, role, audience, directory or signing material of its own', async () => {
    await exchangeStaffToken(identity({ tid: DIRECTORY_B }), TENANTS.B.host, NOW);
    expect(Object.keys(seenExchanges[0]?.body as object)).toEqual(['idToken']);
  });

  it.each([null, '', 'tenant-a.example.test/evil', 'a b', 'user@tenant-a.example.test'])(
    'does not call the back end for the host %j',
    async (host) => {
      expect((await failure(exchangeStaffToken(identity(), host, NOW))).reason).toBe('unavailable');
      expect(seenExchanges).toHaveLength(0);
    },
  );

  it.each(['', ' ', 'x'.repeat(8193)])('does not call the back end for an identity token of %j characters', async (token) => {
    expect((await failure(exchangeStaffToken(token, TENANTS.A.host, NOW))).reason).toBe('refused');
    expect(seenExchanges).toHaveLength(0);
  });
});

describe('exchangeStaffToken: what comes back', () => {
  it('is the session material: role, tenant, subject, services, token and expiry', async () => {
    const exp = inAnHour();
    answer(issued({ claims: { exp, sub: 'stf-abc', services: [] }, expiresAt: iso(exp) }));
    const grant = await exchangeStaffToken(identity(), TENANTS.A.host, NOW);
    expect(grant).toEqual({
      role: 'advisor',
      tenantId: TENANTS.A.id,
      sub: 'stf-abc',
      services: [],
      backendToken: expect.any(String),
      expiresAt: iso(exp),
    });
    expect(claimsOf(grant.backendToken).tenant).toBe(TENANTS.A.id);
  });

  it('is the tenant of the host, for each of two tenants and the same person', async () => {
    const a = await exchangeStaffToken(identity(), TENANTS.A.host, NOW);
    const b = await exchangeStaffToken(identity({ tid: DIRECTORY_B }), TENANTS.B.host, NOW);
    expect([a.tenantId, b.tenantId]).toEqual([TENANTS.A.id, TENANTS.B.id]);
    expect(a.backendToken).not.toBe(b.backendToken);
  });

  it.each(['advisor', 'clinical', 'lead', 'owner', 'exec', 'audit', 'tenant-admin', 'network-admin'])('accepts the staff role %s', async (role) => {
    answer(issued({ role, claims: { role } }));
    expect((await exchangeStaffToken(identity(), TENANTS.A.host, NOW)).role).toBe(role);
  });

  it('ignores every other field of the answer and never copies it', async () => {
    answer({ ...issued(), tenant: 'trust-b', epoch: 3, name: 'Sample Staff', email: 'x@example.test' });
    const grant = await exchangeStaffToken(identity(), TENANTS.A.host, NOW);
    expect(JSON.stringify(grant)).not.toMatch(/trust-b|Sample Staff|example\.test/);
    expect(Object.keys(grant).sort()).toEqual(['backendToken', 'expiresAt', 'role', 'services', 'sub', 'tenantId']);
  });
});

describe('exchangeStaffToken: a refusal is one word, and says nothing else', () => {
  it('reads a 403 as refused', async () => {
    expect((await failure(exchangeStaffToken(identity({ roles: [] }), TENANTS.A.host, NOW))).reason).toBe('refused');
  });

  it('reads a person of another directory, on this host, as refused', async () => {
    expect((await failure(exchangeStaffToken(identity({ tid: DIRECTORY_B }), TENANTS.A.host, NOW))).reason).toBe('refused');
  });

  it('reads a host no tenant owns as not-found', async () => {
    expect((await failure(exchangeStaffToken(identity(), 'nobody.example.test', NOW))).reason).toBe('not-found');
  });

  it.each([429, 500, 502, 503])('reads a %s as unavailable', async (status) => {
    answer({ resourceType: 'OperationOutcome', issue: [] }, { status });
    expect((await failure(exchangeStaffToken(identity(), TENANTS.A.host, NOW))).reason).toBe('unavailable');
  });

  it.each([400, 401, 418])('reads a %s as unavailable, never as a person refused', async (status) => {
    answer({}, { status });
    expect((await failure(exchangeStaffToken(identity(), TENANTS.A.host, NOW))).reason).toBe('unavailable');
  });

  it('reads a back end that cannot be reached as unavailable', async () => {
    server.use(http.post(EXCHANGE_URL, () => HttpResponse.error()));
    expect((await failure(exchangeStaffToken(identity(), TENANTS.A.host, NOW))).reason).toBe('unavailable');
  });

  it('carries no token, host or tenant in the error', async () => {
    const id = identity({ roles: [] });
    const error = await failure(exchangeStaffToken(id, TENANTS.A.host, NOW));
    expect(error.message).toBe('The token exchange failed.');
    expect(JSON.stringify([error.message, error.reason, error.name])).not.toContain(id);
    expect(String(error.stack)).not.toContain(id);
  });
});

describe('exchangeStaffToken: an answer it does not trust is bad-answer, not a session', () => {
  const bad = async (body: unknown) => {
    answer(body);
    return (await failure(exchangeStaffToken(identity(), TENANTS.A.host, NOW))).reason;
  };

  it.each([
    ['no token', { ...issued(), token: undefined }],
    ['a token that is not text', { ...issued(), token: 7 }],
    ['a token that is not a token', { ...issued(), token: 'not-a-token' }],
    ['no role', { ...issued(), role: undefined }],
    ['no expiry', { ...issued(), expiresAt: undefined }],
    ['an expiry that is not a date', { ...issued(), expiresAt: 'tomorrow' }],
    ['an expiry that has passed', { ...issued({ claims: { exp: Math.floor(Date.now() / 1000) - 10 }, expiresAt: iso(Math.floor(Date.now() / 1000) - 10) }) }],
    ['a role that is a platform role', issued({ role: 'platform-operator', claims: { role: 'platform-operator' } })],
    ['the support role', issued({ role: 'support', claims: { role: 'support' } })],
    ['a wall role', issued({ role: 'wall', claims: { role: 'wall' } })],
    ['a reporter role', issued({ role: 'reporter', claims: { role: 'reporter' } })],
    ['a role that is not a role', issued({ role: 'root', claims: { role: 'root' } })],
    ['a role the token does not hold', issued({ role: 'lead', claims: { role: 'advisor' } })],
    ['a token for no tenant', issued({ claims: { tenant: undefined } })],
    ['a token for a network', issued({ claims: { tenant: 'net-capacity' } })],
    ['a token for the operator audience', issued({ claims: { aud: 'diucs-ops' } })],
    ['a token with no audience', issued({ claims: { aud: undefined } })],
    ['a token that ends at another time than the answer says', issued({ expiresAt: iso(inAnHour() + 600) })],
    ['an answer that is a list', []],
    ['an answer that is text', 'ok'],
    ['an answer that is null', null],
  ])('refuses %s', async (_name, body) => {
    expect(await bad(body)).toBe('bad-answer');
  });

  it('refuses an answer that is not JSON', async () => {
    server.use(http.post(EXCHANGE_URL, () => new HttpResponse('<html>', { status: 200, headers: { 'Content-Type': 'text/html' } })));
    expect((await failure(exchangeStaffToken(identity(), TENANTS.A.host, NOW))).reason).toBe('bad-answer');
  });

  it('refuses an answer of absurd size', async () => {
    server.use(http.post(EXCHANGE_URL, () => HttpResponse.json({ ...issued(), pad: 'x'.repeat(200_000) })));
    expect((await failure(exchangeStaffToken(identity(), TENANTS.A.host, NOW))).reason).toBe('bad-answer');
  });
});
