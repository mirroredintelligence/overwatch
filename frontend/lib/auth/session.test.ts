// @vitest-environment node
import { CompactEncrypt, EncryptJWT } from 'jose';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  cookieWrites,
  cookiesMock,
  lastWrite,
  requestWithCookies,
  resetCookieWrites,
  seedCookies,
  setRequestHost,
  TEST_SESSION_SECRET,
} from '@/test/cookies';
import { TENANTS } from '@/test/tenants';
import {
  createSession,
  destroySession,
  getSession,
  ROLES,
  SESSION_COOKIE,
  sealSession,
  sessionFromRequest,
  unsealSession,
  type Session,
} from './session';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const NOW = new Date('2026-10-23T13:12:00.000Z');
const TOKEN = 'backend-token-sample-value';

// An expiry that is in the future whenever the test runs.
const FUTURE = new Date(Date.now() + 3_600_000).toISOString();
function soon() {
  return FUTURE;
}

function sample(overrides: Partial<Session> = {}): Session {
  return {
    role: 'advisor',
    services: ['svc-1', 'svc-2'],
    tenantId: TENANTS.A.id,
    host: TENANTS.A.host,
    sub: 'user-1',
    backendToken: TOKEN,
    expiresAt: '2026-10-23T21:12:00.000Z',
    ...overrides,
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

describe('sealSession and unsealSession', () => {
  it('round-trips a session', async () => {
    const session = sample({ device: 'dev-1' });
    const sealed = await sealSession(session, NOW);
    expect(await unsealSession(sealed, NOW)).toEqual(session);
  });

  it('round-trips a session without a device', async () => {
    const session = sample();
    const back = await unsealSession(await sealSession(session, NOW), NOW);
    expect(back).toEqual(session);
    expect(back).not.toHaveProperty('device');
  });

  it('does not show the back-end token or the sub in the sealed string', async () => {
    const sealed = await sealSession(sample(), NOW);
    expect(sealed).not.toContain(TOKEN);
    expect(Buffer.from(sealed.split('.')[3] ?? '', 'base64url').toString()).not.toContain(TOKEN);
  });

  it('returns null for a modified string', async () => {
    const sealed = await sealSession(sample(), NOW);
    const parts = sealed.split('.');
    // Change a character in the middle of the ciphertext segment. The last
    // character holds unused base64url bits, so changing it can change nothing.
    const ct = parts[3] ?? '';
    const mid = Math.floor(ct.length / 2);
    parts[3] = ct.slice(0, mid) + (ct[mid] === 'A' ? 'B' : 'A') + ct.slice(mid + 1);
    expect(await unsealSession(parts.join('.'), NOW)).toBeNull();
  });

  it('returns null for text that is not a sealed session', async () => {
    expect(await unsealSession('', NOW)).toBeNull();
    expect(await unsealSession('not-a-token', NOW)).toBeNull();
  });

  it('returns null for an expired session', async () => {
    const sealed = await sealSession(sample({ expiresAt: '2026-10-23T13:30:00.000Z' }), NOW);
    expect(await unsealSession(sealed, new Date('2026-10-23T13:30:01.000Z'))).toBeNull();
  });

  it('returns null at the exact expiry instant', async () => {
    const sealed = await sealSession(sample({ expiresAt: '2026-10-23T13:30:00.000Z' }), NOW);
    expect(await unsealSession(sealed, new Date('2026-10-23T13:30:00.000Z'))).toBeNull();
    expect(await unsealSession(sealed, new Date('2026-10-23T13:29:59.000Z'))).not.toBeNull();
  });

  it('refuses to seal a session that has already expired', async () => {
    await expect(
      sealSession(sample({ expiresAt: '2026-10-23T13:00:00.000Z' }), NOW),
    ).rejects.toThrow(/expir/i);
  });

  it('refuses to seal a session that expires at this very instant', async () => {
    await expect(sealSession(sample({ expiresAt: NOW.toISOString() }), NOW)).rejects.toThrow(
      /expir/i,
    );
  });

  it('refuses to seal an expiry that is not a date', async () => {
    await expect(sealSession(sample({ expiresAt: 'tomorrow' }), NOW)).rejects.toThrow(/expir/i);
  });

  it('returns null when the string was sealed with another secret', async () => {
    const sealed = await sealSession(sample(), NOW);
    vi.stubEnv('SESSION_SECRET', Buffer.alloc(32, 9).toString('base64'));
    expect(await unsealSession(sealed, NOW)).toBeNull();
  });

  it('returns null for a string that uses another encryption algorithm', async () => {
    const key = Buffer.alloc(16, 7);
    const other = await new CompactEncrypt(new TextEncoder().encode(JSON.stringify(sample())))
      .setProtectedHeader({ alg: 'dir', enc: 'A128GCM' })
      .encrypt(key);
    expect(await unsealSession(other, NOW)).toBeNull();
  });

  it.each([
    ['A256KW + A256GCM', { alg: 'A256KW', enc: 'A256GCM' }],
    ['A256KW + A128GCM', { alg: 'A256KW', enc: 'A128GCM' }],
    // A128CBC-HS256 takes a 32-byte key, so the real secret is a valid key for
    // it: only the enc pin can refuse this one.
    ['dir + A128CBC-HS256', { alg: 'dir', enc: 'A128CBC-HS256' }],
  ])('returns null for a string sealed with the real secret using %s', async (_label, header) => {
    const real = Buffer.from(TEST_SESSION_SECRET, 'base64');
    const other = await new EncryptJWT({ ...sample() })
      .setProtectedHeader(header)
      .setExpirationTime(Math.floor(NOW.getTime() / 1000) + 600)
      .encrypt(real);
    expect(await unsealSession(other, NOW)).toBeNull();
  });

  it('returns null for dir + A128GCM sealed with a 16-byte key derived from the real secret', async () => {
    const key = Buffer.from(TEST_SESSION_SECRET, 'base64').subarray(0, 16);
    const other = await new EncryptJWT({ ...sample() })
      .setProtectedHeader({ alg: 'dir', enc: 'A128GCM' })
      .setExpirationTime(Math.floor(NOW.getTime() / 1000) + 600)
      .encrypt(key);
    expect(await unsealSession(other, NOW)).toBeNull();
  });

  it('throws for an empty cookie when SESSION_SECRET is missing or malformed, never null', async () => {
    for (const value of ['', 'short']) {
      vi.stubEnv('SESSION_SECRET', value);
      await expect(unsealSession('', NOW)).rejects.toThrow(/SESSION_SECRET/);
    }
  });

  it('returns null for a correctly sealed payload that is not a session', async () => {
    const key = Buffer.from(TEST_SESSION_SECRET, 'base64');
    const seal = (claims: Record<string, unknown>) =>
      new EncryptJWT(claims)
        .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
        .setExpirationTime(Math.floor(NOW.getTime() / 1000) + 600)
        .encrypt(key);
    const good = { ...sample() };
    expect(await unsealSession(await seal(good), NOW)).toEqual(sample());
    for (const bad of [
      { ...good, tenantId: undefined },
      { ...good, tenantId: '' },
      { ...good, tenantId: 7 },
      { ...good, tenantId: 'net-capacity' },
      { ...good, tenantId: 'Trust A' },
      { ...good, tenantId: ['trust-a'] },
      { ...good, host: undefined },
      { ...good, host: '' },
      { ...good, host: 'tenant-a.example.test/evil' },
      { ...good, host: 7 },
      { ...good, role: 'admin' },
      { ...good, role: undefined },
      { ...good, services: 'svc-1' },
      { ...good, services: [1] },
      { ...good, sub: '' },
      { ...good, sub: 5 },
      { ...good, backendToken: '' },
      { ...good, backendToken: undefined },
      { ...good, device: 5 },
      { ...good, expiresAt: 'tomorrow' },
      { ...good, expiresAt: undefined },
    ]) {
      expect(await unsealSession(await seal(bad), NOW)).toBeNull();
    }
  });

  it('returns null when expiresAt is this instant, even if the sealed exp claim is later', async () => {
    const key = Buffer.from(TEST_SESSION_SECRET, 'base64');
    const sealed = await new EncryptJWT({ ...sample({ expiresAt: NOW.toISOString() }) })
      .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
      .setExpirationTime(Math.floor(NOW.getTime() / 1000) + 600)
      .encrypt(key);
    expect(await unsealSession(sealed, NOW)).toBeNull();
    expect(await unsealSession(sealed, new Date(NOW.getTime() - 1))).not.toBeNull();
  });

  it('returns null when the jose exp claim has passed, even if expiresAt is still later', async () => {
    // Checked by jose (exp), not by our expiresAt comparison: expiresAt is an
    // hour ahead, so only the exp check can refuse this token.
    const key = Buffer.from(TEST_SESSION_SECRET, 'base64');
    const sealed = await new EncryptJWT({ ...sample({ expiresAt: new Date(NOW.getTime() + 3_600_000).toISOString() }) })
      .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
      .setExpirationTime(Math.floor(NOW.getTime() / 1000) - 60)
      .encrypt(key);
    expect(await unsealSession(sealed, NOW)).toBeNull();
  });

  it('accepts every role in the contract and no other', async () => {
    expect([...ROLES]).toEqual([
      'reporter',
      'advisor',
      'clinical',
      'lead',
      'owner',
      'exec',
      'wall',
      'anonymous-link',
      'support',
      'audit',
      'tenant-admin',
      'network-admin',
    ]);
    for (const role of ROLES) {
      const back = await unsealSession(await sealSession(sample({ role }), NOW), NOW);
      expect(back?.role).toBe(role);
    }
  });

  it.each([
    ['missing', undefined],
    ['empty', ''],
    ['not base64 of 32 bytes', Buffer.alloc(16, 1).toString('base64')],
    ['too long', Buffer.alloc(33, 1).toString('base64')],
    ['not base64', '!!!'],
  ])('throws an error that names SESSION_SECRET when it is %s', async (_label, value) => {
    if (value === undefined) vi.stubEnv('SESSION_SECRET', undefined as unknown as string);
    else vi.stubEnv('SESSION_SECRET', value);
    const attempt = sealSession(sample(), NOW);
    await expect(attempt).rejects.toThrow(/SESSION_SECRET/);
    await expect(attempt).rejects.not.toThrow(String(value || 'never-matches-empty'));
    await expect(unsealSession('a.b.c.d.e', NOW)).rejects.toThrow(/SESSION_SECRET/);
  });
});

describe('sessionFromRequest', () => {
  it('reads the session from the Cookie header', async () => {
    const sealed = await sealSession(sample({ expiresAt: soon() }), new Date());
    const request = requestWithCookies(`https://${TENANTS.A.host}/x`, {
      other: '1',
      [SESSION_COOKIE]: sealed,
    });
    expect(await sessionFromRequest(request)).toEqual(sample({ expiresAt: soon() }));
  });

  it('returns null with no cookie, an empty cookie or a bad cookie', async () => {
    expect(await sessionFromRequest(new Request(`https://${TENANTS.A.host}/x`))).toBeNull();
    expect(
      await sessionFromRequest(requestWithCookies(`https://${TENANTS.A.host}/x`, { [SESSION_COOKIE]: '' })),
    ).toBeNull();
    expect(
      await sessionFromRequest(requestWithCookies(`https://${TENANTS.A.host}/x`, { [SESSION_COOKIE]: 'x.y' })),
    ).toBeNull();
  });
});

describe('createSession', () => {
  it('sets a cookie that is HttpOnly, SameSite=Strict, Path=/ and Secure', async () => {
    await createSession(sample({ expiresAt: new Date(Date.now() + 3_600_000).toISOString() }));
    const write = lastWrite(SESSION_COOKIE);
    expect(write).toBeDefined();
    expect(write?.options).toMatchObject({
      httpOnly: true,
      sameSite: 'strict',
      path: '/',
      secure: true,
    });
    expect(write?.options).not.toHaveProperty('domain');
  });

  it('is not Secure only when NODE_ENV is development', async () => {
    const expiresAt = new Date(Date.now() + 3_600_000).toISOString();
    vi.stubEnv('NODE_ENV', 'development');
    await createSession(sample({ expiresAt }));
    expect(lastWrite(SESSION_COOKIE)?.options.secure).toBe(false);
    for (const env of ['production', 'test']) {
      vi.stubEnv('NODE_ENV', env);
      await createSession(sample({ expiresAt }));
      expect(lastWrite(SESSION_COOKIE)?.options.secure).toBe(true);
    }
  });

  it('lasts until the session expires, to the second', async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(NOW);
      await createSession(sample({ expiresAt: '2026-10-23T13:12:30.900Z' }));
      expect(lastWrite(SESSION_COOKIE)?.options.maxAge).toBe(30);
    } finally {
      vi.useRealTimers();
    }
  });

  it('stores a value that unseals to the session', async () => {
    const session = sample({ expiresAt: new Date(Date.now() + 3_600_000).toISOString() });
    await createSession(session);
    const value = lastWrite(SESSION_COOKIE)?.value ?? '';
    expect(await unsealSession(value)).toEqual(session);
  });
});

describe('destroySession', () => {
  it('expires the cookie with the same attributes', async () => {
    await destroySession();
    const write = lastWrite(SESSION_COOKIE);
    expect(write?.value).toBe('');
    expect(write?.options).toMatchObject({
      maxAge: 0,
      httpOnly: true,
      sameSite: 'strict',
      path: '/',
      secure: true,
    });
  });
});

describe('getSession', () => {
  it('returns null when the cookie store has no session cookie', async () => {
    expect(await getSession()).toBeNull();
  });

  it('reads the session cookie from the Next cookie store', async () => {
    const sealed = await sealSession(sample({ expiresAt: soon() }), new Date());
    const { fakeCookieStore } = await import('@/test/cookies');
    vi.spyOn(fakeCookieStore, 'get').mockImplementation((name: string) =>
      name === SESSION_COOKIE ? { name, value: sealed } : undefined,
    );
    expect(await getSession()).toEqual(sample({ expiresAt: soon() }));
  });
});

describe('logging', () => {
  it('never writes the cookie or the back-end token to the console', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    const sealed = await sealSession(sample({ expiresAt: soon() }), new Date());
    await unsealSession(`${sealed}x`);
    await unsealSession('junk');
    await createSession(sample({ expiresAt: new Date(Date.now() + 3_600_000).toISOString() }));
    await destroySession();
    expect(cookieWrites.length).toBeGreaterThan(0);
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });
});


describe('the tenant in the session (TEN-044)', () => {
  it('round-trips the tenant and the host the session was made on', async () => {
    const back = await unsealSession(await sealSession(sample({ tenantId: TENANTS.B.id, host: TENANTS.B.host }), NOW), NOW);
    expect(back).toMatchObject({ tenantId: TENANTS.B.id, host: TENANTS.B.host });
  });

  it('refuses to seal a session with no tenant, a network id or a malformed tenant id', async () => {
    for (const tenantId of ['', 'net-capacity', 'UPPER', 'a', 'has space', 'x'.repeat(40)]) {
      await expect(sealSession(sample({ tenantId }), NOW)).rejects.toThrow(/tenant/i);
    }
  });

  it('refuses to seal a session with no host or a host that is not a host name', async () => {
    for (const host of ['', 'a.test/path', 'a.test?x=1', 'user@a.test', ' a.test', 'a b.test']) {
      await expect(sealSession(sample({ host }), NOW)).rejects.toThrow(/host/i);
    }
  });

  it('does not show the tenant id in the sealed string', async () => {
    const sealed = await sealSession(sample(), NOW);
    expect(sealed).not.toContain(TENANTS.A.id);
    expect(sealed).not.toContain(TENANTS.A.host);
  });

  it('returns null for a session from before the tenant was in it, sealed with the real key', async () => {
    const key = Buffer.from(TEST_SESSION_SECRET, 'base64');
    const { tenantId: _tenant, host: _host, ...old } = sample();
    void _tenant;
    void _host;
    const sealed = await new EncryptJWT({ ...old })
      .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
      .setExpirationTime(Math.floor(NOW.getTime() / 1000) + 600)
      .encrypt(key);
    expect(await unsealSession(sealed, NOW)).toBeNull();
  });
});

describe('a session is for the host it was made on (TEN-044)', () => {
  const URL_A = `https://${TENANTS.A.host}/x`;
  const URL_B = `https://${TENANTS.B.host}/x`;

  it('is read on its own host', async () => {
    const sealed = await sealSession(sample({ expiresAt: soon() }), new Date());
    const request = requestWithCookies(URL_A, { [SESSION_COOKIE]: sealed }, { headers: { Host: TENANTS.A.host } });
    expect(await sessionFromRequest(request)).toMatchObject({ tenantId: TENANTS.A.id });
  });

  it('is not read on another tenant host, even when the browser sent the cookie there (a cookie set from a sibling sub-domain)', async () => {
    const sealed = await sealSession(sample({ expiresAt: soon() }), new Date());
    const request = requestWithCookies(URL_B, { [SESSION_COOKIE]: sealed }, { headers: { Host: TENANTS.B.host } });
    expect(await sessionFromRequest(request)).toBeNull();
  });

  it('compares the host without case, and with the port it was made on', async () => {
    const sealed = await sealSession(sample({ host: 'tenant-a.example.test:3000', expiresAt: soon() }), new Date());
    const ok = requestWithCookies(URL_A, { [SESSION_COOKIE]: sealed }, { headers: { Host: 'Tenant-A.Example.Test:3000' } });
    expect(await sessionFromRequest(ok)).not.toBeNull();
    const otherPort = requestWithCookies(URL_A, { [SESSION_COOKIE]: sealed }, { headers: { Host: 'tenant-a.example.test:3001' } });
    expect(await sessionFromRequest(otherPort)).toBeNull();
  });

  it('is not read when the request has a host that is not a host name', async () => {
    const sealed = await sealSession(sample({ expiresAt: soon() }), new Date());
    const request = requestWithCookies(URL_A, { [SESSION_COOKIE]: sealed }, { headers: { Host: `${TENANTS.A.host}/evil` } });
    expect(await sessionFromRequest(request)).toBeNull();
  });

  it('is read from the Next cookie store only on its own host', async () => {
    const sealed = await sealSession(sample({ expiresAt: soon() }), new Date());
    seedCookies({ [SESSION_COOKIE]: sealed });
    setRequestHost(TENANTS.A.host);
    expect(await getSession()).toMatchObject({ tenantId: TENANTS.A.id });
    setRequestHost(TENANTS.B.host);
    expect(await getSession()).toBeNull();
  });

  it('is never read through a header that names a tenant', async () => {
    const sealed = await sealSession(sample({ expiresAt: soon() }), new Date());
    const request = requestWithCookies(
      URL_B,
      { [SESSION_COOKIE]: sealed },
      { headers: { Host: TENANTS.B.host, 'X-Tenant-Id': TENANTS.A.id, 'X-Forwarded-Host': TENANTS.A.host } },
    );
    expect(await sessionFromRequest(request)).toBeNull();
  });
});

describe('the reporter’s PIN session and token expiry in the session (W8E, DEC-792)', () => {
  const PIN = 'ps-sample-0123456789abcdefghijklmnopqrstuvw';
  const reporter = (overrides: Partial<Session> = {}) =>
    sample({ role: 'reporter', device: 'D'.repeat(22), pinSession: PIN, tokenExpiresAt: '2026-10-23T13:42:00.000Z', ...overrides });
  const seal = (claims: Record<string, unknown>) =>
    new EncryptJWT(claims)
      .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
      .setExpirationTime(Math.floor(NOW.getTime() / 1000) + 600)
      .encrypt(Buffer.from(TEST_SESSION_SECRET, 'base64'));

  it('round-trips the PIN session and the token’s expiry', async () => {
    const session = reporter();
    expect(await unsealSession(await sealSession(session, NOW), NOW)).toEqual(session);
  });

  it('does not show the PIN session id in the sealed string', async () => {
    expect(await sealSession(reporter(), NOW)).not.toContain(PIN);
  });

  it('is unchanged for a session with neither (a staff session, or a registrant’s token)', async () => {
    const session = sample();
    const read = await unsealSession(await sealSession(session, NOW), NOW);
    expect(read).toEqual(session);
    expect(read).not.toHaveProperty('pinSession');
    expect(read).not.toHaveProperty('tokenExpiresAt');
  });

  it('refuses to seal one of the two without the other', async () => {
    await expect(sealSession(reporter({ tokenExpiresAt: undefined }), NOW)).rejects.toThrow();
    await expect(sealSession(reporter({ pinSession: undefined }), NOW)).rejects.toThrow();
  });

  it('refuses to seal a token expiry that is not a date or a PIN session id that cannot be one', async () => {
    await expect(sealSession(reporter({ tokenExpiresAt: 'soon' }), NOW)).rejects.toThrow();
    await expect(sealSession(reporter({ pinSession: '' }), NOW)).rejects.toThrow();
    await expect(sealSession(reporter({ pinSession: 'x'.repeat(129) }), NOW)).rejects.toThrow();
  });

  it('returns null for a sealed payload with one of the two, or with either of the wrong shape', async () => {
    const good = { ...reporter() };
    expect(await unsealSession(await seal(good), NOW)).toEqual(reporter());
    for (const bad of [
      { ...good, tokenExpiresAt: undefined },
      { ...good, pinSession: undefined },
      { ...good, pinSession: '' },
      { ...good, pinSession: 5 },
      { ...good, pinSession: 'x'.repeat(129) },
      { ...good, tokenExpiresAt: 'soon' },
      { ...good, tokenExpiresAt: 5 },
    ]) {
      expect(await unsealSession(await seal(bad), NOW)).toBeNull();
    }
  });
});
