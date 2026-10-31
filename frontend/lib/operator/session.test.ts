// @vitest-environment node
import { EncryptJWT } from 'jose';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites, seedCookies, setRequestHost, TEST_SESSION_SECRET } from '@/test/cookies';
import { TENANTS } from '@/test/tenants';
import { sealSession, SESSION_COOKIE, unsealSession, type Session } from '@/lib/auth/session';
import {
  createOperatorSession,
  destroyOperatorSession,
  getOperatorSession,
  OPERATOR_COOKIE,
  OPERATOR_ROLES,
  operatorSessionFromRequest,
  sealOperatorSession,
  unsealOperatorSession,
  type OperatorSession,
} from './session';

// The operator's session (TEN-083): who is signed in to the platform console, the role the operator
// directory gave and the back end's operator token, sealed into one HTTP-only cookie of its own. It is a
// different KIND of session from a tenant's: it has no tenant, its cookie has another name and another
// key, and neither kind can be read as the other (DEC-134 items 4 and 5).

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const NOW = new Date('2026-10-30T09:00:00.000Z');
const OPERATOR_HOST = 'console.example.test';

function sample(overrides: Partial<OperatorSession> = {}): OperatorSession {
  return {
    role: 'platform-operator',
    host: OPERATOR_HOST,
    accountRef: 'ops-0123456789abcdef0123456789abcdef',
    backendToken: 'operator-token-sample-value',
    expiresAt: '2026-10-30T10:00:00.000Z',
    ...overrides,
  };
}

function tenantSession(): Session {
  return {
    role: 'tenant-admin',
    tenantId: TENANTS.A.id,
    host: TENANTS.A.host,
    services: [],
    sub: 'stf-0123456789abcdef0123456789abcdef',
    backendToken: 'tenant-token-sample-value',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('the operator roles', () => {
  it('are the two the back end gives an operator, and no tenant role', () => {
    expect([...OPERATOR_ROLES]).toEqual(['platform-operator', 'support']);
  });
});

describe('sealOperatorSession and unsealOperatorSession', () => {
  it('round-trips a session and shows neither the token nor the account reference in the sealed text', async () => {
    const session = sample();
    const sealed = await sealOperatorSession(session, NOW);
    expect(await unsealOperatorSession(sealed, NOW)).toEqual(session);
    expect(sealed).not.toContain(session.backendToken);
    expect(sealed).not.toContain(session.accountRef);
  });

  it('seals a support session too', async () => {
    const session = sample({ role: 'support' });
    expect(await unsealOperatorSession(await sealOperatorSession(session, NOW), NOW)).toEqual(session);
  });

  it('refuses to seal a session that has a tenant, a tenant role, an expired time or no host', async () => {
    await expect(sealOperatorSession({ ...sample(), tenantId: 'trust-a' } as unknown as OperatorSession, NOW)).rejects.toThrow();
    await expect(sealOperatorSession(sample({ role: 'lead' as never }), NOW)).rejects.toThrow();
    await expect(sealOperatorSession(sample({ role: 'tenant-admin' as never }), NOW)).rejects.toThrow();
    await expect(sealOperatorSession(sample({ expiresAt: '2026-10-30T08:00:00.000Z' }), NOW)).rejects.toThrow('expired');
    await expect(sealOperatorSession(sample({ host: 'Not A Host' }), NOW)).rejects.toThrow('host');
    await expect(sealOperatorSession(sample({ backendToken: '' }), NOW)).rejects.toThrow();
  });

  it('is void at its expiry and at a later time', async () => {
    const sealed = await sealOperatorSession(sample(), NOW);
    expect(await unsealOperatorSession(sealed, new Date('2026-10-30T10:00:00.000Z'))).toBeNull();
    expect(await unsealOperatorSession(sealed, new Date('2026-10-30T11:00:00.000Z'))).toBeNull();
  });

  it('is null for text that is not ours, empty text and text sealed with another key', async () => {
    expect(await unsealOperatorSession('', NOW)).toBeNull();
    expect(await unsealOperatorSession('not-a-token', NOW)).toBeNull();
    const sealed = await sealOperatorSession(sample(), NOW);
    vi.stubEnv('SESSION_SECRET', Buffer.alloc(32, 9).toString('base64'));
    expect(await unsealOperatorSession(sealed, NOW)).toBeNull();
  });

  it('is a fault, never "no session", when the secret is missing', async () => {
    const sealed = await sealOperatorSession(sample(), NOW);
    vi.stubEnv('SESSION_SECRET', '');
    await expect(unsealOperatorSession(sealed, NOW)).rejects.toThrow('SESSION_SECRET');
  });

  it('is not a tenant session: a tenant session cookie value is no operator session, and the other way round', async () => {
    const asTenant = await sealSession(tenantSession(), NOW);
    expect(await unsealOperatorSession(asTenant, NOW)).toBeNull();
    const asOperator = await sealOperatorSession(sample(), NOW);
    expect(await unsealSession(asOperator, NOW)).toBeNull();
  });

  it('refuses a payload sealed with the operator key that carries a tenant, another kind or a tenant role', async () => {
    // Sealed by hand, as an attacker who somehow had the derived key would: the unseal still refuses it.
    const { operatorSealingKey } = await import('./session');
    const seal = async (claims: Record<string, unknown>) =>
      new EncryptJWT(claims).setProtectedHeader({ alg: 'dir', enc: 'A256GCM' }).setIssuedAt().setExpirationTime('1h').encrypt(await operatorSealingKey());
    const base = { kind: 'operator', role: 'platform-operator', host: OPERATOR_HOST, accountRef: 'ops-1', backendToken: 'x', expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
    expect(await unsealOperatorSession(await seal(base))).not.toBeNull();
    expect(await unsealOperatorSession(await seal({ ...base, tenantId: 'trust-a' }))).toBeNull();
    expect(await unsealOperatorSession(await seal({ ...base, tenant: 'trust-a' }))).toBeNull();
    expect(await unsealOperatorSession(await seal({ ...base, kind: 'tenant' }))).toBeNull();
    expect(await unsealOperatorSession(await seal({ ...base, role: 'tenant-admin' }))).toBeNull();
    expect(await unsealOperatorSession(await seal({ ...base, role: 'lead' }))).toBeNull();
    expect(await unsealOperatorSession(await seal({ ...base, host: 'Bad Host' }))).toBeNull();
    const { kind: _kind, ...noKind } = base;
    void _kind;
    expect(await unsealOperatorSession(await seal(noKind))).toBeNull();
  });
});

describe('operatorSessionFromRequest', () => {
  it('reads the session only on the host it was made on', async () => {
    const sealed = await sealOperatorSession(sample({ expiresAt: new Date(Date.now() + 3_600_000).toISOString() }), new Date());
    const ok = requestWithCookies(`https://${OPERATOR_HOST}/x`, { [OPERATOR_COOKIE]: sealed }, { headers: { Host: OPERATOR_HOST } });
    expect((await operatorSessionFromRequest(ok))?.role).toBe('platform-operator');
    const other = requestWithCookies(`https://${TENANTS.A.host}/x`, { [OPERATOR_COOKIE]: sealed }, { headers: { Host: TENANTS.A.host } });
    expect(await operatorSessionFromRequest(other)).toBeNull();
  });

  it('does not read the tenant session cookie, and a tenant cookie renamed to the operator one is no session', async () => {
    const tenantSealed = await sealSession(tenantSession(), new Date());
    const named = requestWithCookies(`https://${TENANTS.A.host}/x`, { [SESSION_COOKIE]: tenantSealed }, { headers: { Host: TENANTS.A.host } });
    expect(await operatorSessionFromRequest(named)).toBeNull();
    const renamed = requestWithCookies(`https://${TENANTS.A.host}/x`, { [OPERATOR_COOKIE]: tenantSealed }, { headers: { Host: TENANTS.A.host } });
    expect(await operatorSessionFromRequest(renamed)).toBeNull();
  });

  it('is null with no cookie', async () => {
    expect(await operatorSessionFromRequest(new Request(`https://${OPERATOR_HOST}/x`, { headers: { Host: OPERATOR_HOST } }))).toBeNull();
  });
});

describe('the cookie', () => {
  it('is HttpOnly, Secure and SameSite Strict, for the time left, and its name is not the tenant session’s', async () => {
    expect(OPERATOR_COOKIE).not.toBe(SESSION_COOKIE);
    await createOperatorSession(sample({ expiresAt: new Date(Date.now() + 3_600_000).toISOString() }));
    const write = lastWrite(OPERATOR_COOKIE);
    expect(write?.options).toMatchObject({ httpOnly: true, secure: true, sameSite: 'strict', path: '/' });
    expect(Number(write?.options.maxAge)).toBeGreaterThan(3500);
    expect(Number(write?.options.maxAge)).toBeLessThanOrEqual(3600);
    expect(cookieWrites.map((w) => w.name)).toEqual([OPERATOR_COOKIE]);
  });

  it('is read back for the host of the request and cleared at sign-out', async () => {
    setRequestHost(OPERATOR_HOST);
    await createOperatorSession(sample({ expiresAt: new Date(Date.now() + 3_600_000).toISOString() }));
    expect((await getOperatorSession())?.accountRef).toBe('ops-0123456789abcdef0123456789abcdef');
    setRequestHost(TENANTS.A.host);
    expect(await getOperatorSession()).toBeNull();
    setRequestHost(OPERATOR_HOST);
    await destroyOperatorSession();
    expect(lastWrite(OPERATOR_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0, httpOnly: true } });
    expect(await getOperatorSession()).toBeNull();
  });

  it('is not read from a tenant session cookie in the jar', async () => {
    setRequestHost(TENANTS.A.host);
    seedCookies({ [SESSION_COOKIE]: await sealSession(tenantSession(), new Date()) });
    expect(await getOperatorSession()).toBeNull();
  });
});
