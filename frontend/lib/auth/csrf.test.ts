// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  cookiesMock,
  lastWrite,
  requestWithCookies,
  resetCookieWrites,
  TEST_SESSION_SECRET,
} from '@/test/cookies';
import { sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { CSRF_COOKIE, CSRF_HEADER, checkCsrf, clearCsrf, csrfTokenFor, issueCsrf, verifyCsrfToken } from './csrf';
import type { Session } from './session';

const timingSafeEqual = vi.hoisted(() => vi.fn());

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

vi.mock('node:crypto', async (importOriginal) => {
  const real = await importOriginal<typeof import('node:crypto')>();
  timingSafeEqual.mockImplementation(real.timingSafeEqual);
  return { ...real, default: { ...real, timingSafeEqual }, timingSafeEqual };
});

beforeEach(() => {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  resetCookieWrites();
  cookiesMock.mockClear();
  timingSafeEqual.mockClear();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// The CSRF token is tied to the session it was issued for (TEN-046, audit D 3.6): the person, the
// and the tenant and host. A cookie and a header that merely match prove nothing.
const URL_ = `https://${TENANTS.A.host}/api/bff/x`;
// SESSION_SECRET is set here as well, so the token below can be made before the first test starts.
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const NONCE = 'N'.repeat(43);
const SESSION: Session = sessionFor(TENANTS.A, 'advisor', { sub: 'stf-person-1' });
const TOKEN = await csrfTokenFor(SESSION, NONCE);

function post(headerValue: string | null, cookie: string | null, session: Session = SESSION): { request: Request; session: Session } {
  const headers = new Headers();
  if (headerValue !== null) headers.set(CSRF_HEADER, headerValue);
  return {
    request: requestWithCookies(URL_, cookie === null ? {} : { [CSRF_COOKIE]: cookie }, { method: 'POST', headers }),
    session,
  };
}

const check = async (headerValue: string | null, cookie: string | null, session: Session = SESSION) => {
  const made = post(headerValue, cookie, session);
  return checkCsrf(made.request, made.session);
};

describe('csrfTokenFor and verifyCsrfToken', () => {
  it('is a nonce and a MAC, each 32 bytes of base64url, joined by a dot', async () => {
    expect(TOKEN).toMatch(/^[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}$/);
    expect(TOKEN.startsWith(`${NONCE}.`)).toBe(true);
  });

  it('is the same for the same session and nonce, and different for another nonce', async () => {
    expect(await csrfTokenFor(SESSION, NONCE)).toBe(TOKEN);
    expect(await csrfTokenFor(SESSION, 'M'.repeat(43))).not.toBe(TOKEN);
  });

  it('verifies for the session it was made for', async () => {
    expect(await verifyCsrfToken(SESSION, TOKEN)).toBe(true);
  });

  it.each([
    ['another tenant', { tenantId: TENANTS.B.id }],
    ['another host', { host: TENANTS.B.host }],
    ['another person', { sub: 'stf-person-2' }],
  ])('does not verify for %s', async (_name, change) => {
    expect(await verifyCsrfToken({ ...SESSION, ...change }, TOKEN)).toBe(false);
  });

  it('does not verify when the tenant is the only thing that differs, even with everything else equal (the cross-tenant case)', async () => {
    const b = sessionFor(TENANTS.B, 'advisor', { sub: SESSION.sub, host: SESSION.host });
    expect(b.tenantId).not.toBe(SESSION.tenantId);
    expect(await verifyCsrfToken(b, TOKEN)).toBe(false);
  });

  it('does not verify under another SESSION_SECRET', async () => {
    vi.stubEnv('SESSION_SECRET', Buffer.alloc(32, 9).toString('base64'));
    expect(await verifyCsrfToken(SESSION, TOKEN)).toBe(false);
  });

  it('does not verify a token whose nonce or MAC was changed by one character', async () => {
    const [nonce, mac] = TOKEN.split('.') as [string, string];
    const flip = (value: string) => `${value.slice(0, 5)}${value[5] === 'A' ? 'B' : 'A'}${value.slice(6)}`;
    expect(await verifyCsrfToken(SESSION, `${flip(nonce)}.${mac}`)).toBe(false);
    expect(await verifyCsrfToken(SESSION, `${nonce}.${flip(mac)}`)).toBe(false);
  });

  it.each([
    '',
    'A'.repeat(43),
    `${'A'.repeat(43)}.`,
    `.${'A'.repeat(43)}`,
    `${'A'.repeat(43)}.${'A'.repeat(43)}.${'A'.repeat(43)}`,
    `${'A'.repeat(42)}.${'A'.repeat(43)}`,
    `${'A'.repeat(43)}.${'A'.repeat(44)}`,
    `${'A'.repeat(43)}.${'!'.repeat(43)}`,
  ])('does not verify %j (the old unbound token, or one of the wrong shape)', async (value) => {
    expect(await verifyCsrfToken(SESSION, value)).toBe(false);
  });

  it('does not verify what is not text', async () => {
    for (const value of [null, undefined, 7, {}, [TOKEN]]) {
      expect(await verifyCsrfToken(SESSION, value as unknown as string)).toBe(false);
    }
  });

  it('refuses a nonce of the wrong shape when making a token', async () => {
    await expect(csrfTokenFor(SESSION, 'short')).rejects.toThrow();
  });

  it('throws, naming the variable, when SESSION_SECRET is missing: a fault is never a pass', async () => {
    vi.stubEnv('SESSION_SECRET', '');
    await expect(verifyCsrfToken(SESSION, TOKEN)).rejects.toThrow(/SESSION_SECRET/);
  });

  it('shows no part of the session in the token', async () => {
    for (const text of [SESSION.sub, SESSION.tenantId, SESSION.host]) {
      expect(TOKEN).not.toContain(text);
      expect(Buffer.from(TOKEN.replace('.', ''), 'base64url').toString('latin1')).not.toContain(text);
    }
  });
});

describe('checkCsrf', () => {
  it('passes when the header equals the cookie and the token is the session’s', async () => {
    expect(await check(TOKEN, TOKEN)).toBe(true);
  });

  it('fails when the header is missing', async () => {
    expect(await check(null, TOKEN)).toBe(false);
  });

  it('fails when the header is empty, even if the cookie is empty', async () => {
    expect(await check('', '')).toBe(false);
    expect(await check('', TOKEN)).toBe(false);
  });

  it('fails when the header differs from the cookie, even when both are valid for the session', async () => {
    const other = await csrfTokenFor(SESSION, 'M'.repeat(43));
    expect(await verifyCsrfToken(SESSION, other)).toBe(true);
    expect(await check(other, TOKEN)).toBe(false);
    expect(await check(TOKEN, other)).toBe(false);
  });

  it('fails when the cookie is missing', async () => {
    expect(await check(TOKEN, null)).toBe(false);
  });

  it('fails for a header and cookie that match each other but were not made for this session (a planted pair)', async () => {
    const planted = 'A'.repeat(43);
    expect(await check(planted, planted)).toBe(false);
    expect(await check(`${planted}.${planted}`, `${planted}.${planted}`)).toBe(false);
  });

  it('fails for a pair that was made for another tenant’s session', async () => {
    const b = sessionFor(TENANTS.B, 'advisor', { sub: SESSION.sub, host: SESSION.host });
    const forB = await csrfTokenFor(b, NONCE);
    expect(await check(forB, forB, SESSION)).toBe(false);
    expect(await check(forB, forB, b)).toBe(true);
  });

  it('fails for a pair that was made for another person or another host', async () => {
    for (const change of [{ sub: 'stf-person-2' }, { host: TENANTS.B.host }]) {
      const old = await csrfTokenFor({ ...SESSION, ...change }, NONCE);
      expect(await check(old, old)).toBe(false);
    }
  });

  it('reads the header by its name regardless of case', async () => {
    const request = requestWithCookies(URL_, { [CSRF_COOKIE]: TOKEN }, { method: 'POST', headers: { 'x-csrf-token': TOKEN } });
    expect(await checkCsrf(request, SESSION)).toBe(true);
    expect(CSRF_HEADER).toBe('X-CSRF-Token');
  });

  it('compares header and cookie, and the MAC, with timingSafeEqual', async () => {
    expect(await check(TOKEN, TOKEN)).toBe(true);
    expect(timingSafeEqual.mock.calls.length).toBeGreaterThanOrEqual(2);
    timingSafeEqual.mockClear();
    await check(await csrfTokenFor(SESSION, 'M'.repeat(43)), TOKEN);
    expect(timingSafeEqual).toHaveBeenCalled();
  });

  it('never calls the comparison with buffers of unequal length', async () => {
    await check('short', TOKEN);
    await check(TOKEN, 'short');
    await check(`${TOKEN}A`, TOKEN);
    for (const [a, b] of timingSafeEqual.mock.calls as [Buffer, Buffer][]) {
      expect(a.length).toBe(b.length);
    }
  });

  it('is not fooled by another cookie of similar name', async () => {
    const request = requestWithCookies(URL_, { [`x${CSRF_COOKIE}`]: TOKEN }, { method: 'POST', headers: { [CSRF_HEADER]: TOKEN } });
    expect(await checkCsrf(request, SESSION)).toBe(false);
  });

  it('is not fooled by the link page’s cookie: it is another cookie with another name', async () => {
    const request = requestWithCookies(URL_, { diucs_link_csrf: TOKEN }, { method: 'POST', headers: { [CSRF_HEADER]: TOKEN } });
    expect(await checkCsrf(request, SESSION)).toBe(false);
  });

  it('throws, never passes, when SESSION_SECRET is missing', async () => {
    vi.stubEnv('SESSION_SECRET', '');
    await expect(check(TOKEN, TOKEN)).rejects.toThrow(/SESSION_SECRET/);
  });
});

describe('issueCsrf', () => {
  it('returns a token made for the session and sets it as the cookie', async () => {
    const token = await issueCsrf(SESSION);
    expect(token).toMatch(/^[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}$/);
    expect(await verifyCsrfToken(SESSION, token)).toBe(true);
    expect(lastWrite(CSRF_COOKIE)?.value).toBe(token);
  });

  it('gives a different token each time, each valid for the session', async () => {
    const one = await issueCsrf(SESSION);
    const two = await issueCsrf(SESSION);
    expect(one).not.toBe(two);
    expect(await verifyCsrfToken(SESSION, two)).toBe(true);
  });

  it('gives a token that does not verify for another tenant’s session', async () => {
    const token = await issueCsrf(SESSION);
    expect(await verifyCsrfToken(sessionFor(TENANTS.B, 'advisor', { sub: SESSION.sub, host: SESSION.host }), token)).toBe(false);
  });

  it('sets a cookie the page script can read, SameSite=Strict, Path=/, Secure, no Domain', async () => {
    await issueCsrf(SESSION);
    const options = lastWrite(CSRF_COOKIE)?.options ?? {};
    expect(options).toMatchObject({ sameSite: 'strict', path: '/', secure: true });
    expect(options.httpOnly).toBeFalsy();
    expect(options).not.toHaveProperty('domain');
  });

  it('is not Secure only in development', async () => {
    vi.stubEnv('NODE_ENV', 'development');
    await issueCsrf(SESSION);
    expect(lastWrite(CSRF_COOKIE)?.options.secure).toBe(false);
  });

  it('takes its nonce from crypto.getRandomValues', async () => {
    const spy = vi.spyOn(crypto, 'getRandomValues').mockImplementation(((a: Uint8Array) => {
      a.fill(255);
      return a;
    }) as never);
    const token = await issueCsrf(SESSION);
    expect(spy).toHaveBeenCalled();
    expect(token.startsWith(`${Buffer.alloc(32, 255).toString('base64url')}.`)).toBe(true);
  });

  it('puts no tenant, host, subject or role in the cookie value or its attributes', async () => {
    await issueCsrf(SESSION);
    const write = lastWrite(CSRF_COOKIE);
    const everything = JSON.stringify([write?.value, write?.options]);
    for (const text of [SESSION.tenantId, SESSION.host, SESSION.sub, SESSION.role]) expect(everything).not.toContain(text);
  });

  it('writes nothing to the console', async () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    await issueCsrf(SESSION);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe('clearCsrf', () => {
  it('expires the cookie with the same attributes', async () => {
    await clearCsrf();
    const write = lastWrite(CSRF_COOKIE);
    expect(write?.value).toBe('');
    expect(write?.options).toMatchObject({ maxAge: 0, sameSite: 'strict', path: '/', secure: true });
  });
});
