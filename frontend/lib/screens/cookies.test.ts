// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cookieWrites, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { sealSession } from '@/lib/auth/session';
import {
  DEVICE_COOKIE,
  deviceFrom,
  forgetDevice,
  forgetPairing,
  pairingFrom,
  PAIRING_COOKIE,
  rememberDevice,
  rememberPairing,
} from './cookies';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The pairing secret and the device token live in two sealed cookies the browser cannot read or
// change, each with a key of its own (derived from the session secret), so neither can pass as the
// other or as a session, and only the screen routes ever receive them.

const PAIRING = { pairingId: 'pairing-1', screenSecret: 'screen-secret-1' };
const URL_ = 'https://tenant-a.example.test/api/bff/screens/pairing';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
});
afterEach(() => vi.unstubAllEnvs());

async function sealedPairing() {
  await rememberPairing(PAIRING);
  return lastWrite(PAIRING_COOKIE)!;
}

describe('the pairing cookie', () => {
  it('is HttpOnly, Secure, SameSite Strict, limited to the screen routes and gone in ten minutes', async () => {
    const write = await sealedPairing();
    expect(write.options).toMatchObject({ httpOnly: true, secure: true, sameSite: 'strict', path: '/api/bff/screens' });
    expect(Number(write.options.maxAge)).toBeGreaterThan(0);
    expect(Number(write.options.maxAge)).toBeLessThanOrEqual(600);
  });

  it('holds the pairing id and the secret sealed: neither is readable in the value', async () => {
    const { value } = await sealedPairing();
    expect(value).not.toContain(PAIRING.pairingId);
    expect(value).not.toContain(PAIRING.screenSecret);
    expect(Buffer.from(value.split('.')[0] ?? '', 'base64url').toString()).not.toContain('alg":"none');
    expect(await pairingFrom(requestWithCookies(URL_, { [PAIRING_COOKIE]: value }))).toEqual(PAIRING);
  });

  it('gives nothing for no cookie, a changed cookie, a session cookie, a device cookie or a cookie of an older secret', async () => {
    const { value } = await sealedPairing();
    expect(await pairingFrom(requestWithCookies(URL_, {}))).toBeNull();
    expect(await pairingFrom(requestWithCookies(URL_, { [PAIRING_COOKIE]: value.slice(0, -4) + 'AAAA' }))).toBeNull();
    expect(await pairingFrom(requestWithCookies(URL_, { [PAIRING_COOKIE]: 'garbage' }))).toBeNull();
    const session = await sealSession({ role: 'wall', services: [], sub: 'dev-1', backendToken: 'a.b.c', expiresAt: new Date(Date.now() + 3_600_000).toISOString() });
    expect(await pairingFrom(requestWithCookies(URL_, { [PAIRING_COOKIE]: session }))).toBeNull();
    await rememberDevice('device-token-for-screen-one');
    const device = lastWrite(DEVICE_COOKIE)!.value;
    expect(await pairingFrom(requestWithCookies(URL_, { [PAIRING_COOKIE]: device }))).toBeNull();
    vi.stubEnv('SESSION_SECRET', Buffer.alloc(32, 8).toString('base64'));
    expect(await pairingFrom(requestWithCookies(URL_, { [PAIRING_COOKIE]: value }))).toBeNull();
  });

  it('is void after ten minutes', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    const { value } = await sealedPairing();
    vi.setSystemTime(Date.now() + 11 * 60_000);
    expect(await pairingFrom(requestWithCookies(URL_, { [PAIRING_COOKIE]: value }))).toBeNull();
    vi.useRealTimers();
  });

  it('is cleared by writing it empty with no life', async () => {
    await forgetPairing();
    expect(lastWrite(PAIRING_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0, path: '/api/bff/screens', httpOnly: true } });
  });

  it('fails when there is no session secret, rather than reading as no cookie', async () => {
    const { value } = await sealedPairing();
    vi.stubEnv('SESSION_SECRET', '');
    await expect(pairingFrom(requestWithCookies(URL_, { [PAIRING_COOKIE]: value }))).rejects.toThrow('SESSION_SECRET');
  });
});

describe('the device cookie', () => {
  it('is HttpOnly, Secure, SameSite Strict and limited to the screen routes, and lasts until the screen is revoked', async () => {
    await rememberDevice('device-token-for-screen-one');
    const write = lastWrite(DEVICE_COOKIE)!;
    expect(write.options).toMatchObject({ httpOnly: true, secure: true, sameSite: 'strict', path: '/api/bff/screens' });
    expect(Number(write.options.maxAge)).toBeGreaterThan(30 * 86400);
    expect(write.value).not.toContain('device-token-for-screen-one');
  });

  it('gives the token back to the screen routes, and nothing for anything that is not a device cookie of ours', async () => {
    await rememberDevice('device-token-for-screen-one');
    const { value } = lastWrite(DEVICE_COOKIE)!;
    expect(await deviceFrom(requestWithCookies(URL_, { [DEVICE_COOKIE]: value }))).toBe('device-token-for-screen-one');
    expect(await deviceFrom(requestWithCookies(URL_, {}))).toBeNull();
    expect(await deviceFrom(requestWithCookies(URL_, { [DEVICE_COOKIE]: 'garbage' }))).toBeNull();
    await rememberPairing(PAIRING);
    expect(await deviceFrom(requestWithCookies(URL_, { [DEVICE_COOKIE]: lastWrite(PAIRING_COOKIE)!.value }))).toBeNull();
  });

  it('is cleared by writing it empty with no life', async () => {
    await forgetDevice();
    expect(lastWrite(DEVICE_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
    expect(cookieWrites).toHaveLength(1);
  });

  it('refuses to hold a token that is not a plain token', async () => {
    for (const bad of ['', 'a b', 'a\r\nb', 'x'.repeat(2000)]) await expect(rememberDevice(bad)).rejects.toThrow();
  });
});
