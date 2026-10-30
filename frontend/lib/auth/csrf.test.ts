// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  cookiesMock,
  lastWrite,
  requestWithCookies,
  resetCookieWrites,
} from '@/test/cookies';
import { CSRF_COOKIE, CSRF_HEADER, checkCsrf, clearCsrf, issueCsrf } from './csrf';

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
  resetCookieWrites();
  cookiesMock.mockClear();
  timingSafeEqual.mockClear();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

const URL_ = 'https://app.test/api/bff/x';
const TOKEN = 'A'.repeat(43);

function post(headerValue: string | null, cookie: string | null): Request {
  const headers = new Headers();
  if (headerValue !== null) headers.set(CSRF_HEADER, headerValue);
  return requestWithCookies(URL_, cookie === null ? {} : { [CSRF_COOKIE]: cookie }, {
    method: 'POST',
    headers,
  });
}

describe('checkCsrf', () => {
  it('passes when the header equals the cookie', () => {
    expect(checkCsrf(post(TOKEN, TOKEN))).toBe(true);
  });

  it('fails when the header is missing', () => {
    expect(checkCsrf(post(null, TOKEN))).toBe(false);
  });

  it('fails when the header is empty, even if the cookie is empty', () => {
    expect(checkCsrf(post('', ''))).toBe(false);
    expect(checkCsrf(post('', TOKEN))).toBe(false);
  });

  it('fails when the header differs from the cookie', () => {
    expect(checkCsrf(post('B'.repeat(43), TOKEN))).toBe(false);
    expect(checkCsrf(post(`${'A'.repeat(42)}B`, TOKEN))).toBe(false);
  });

  it('fails when the lengths differ, without throwing', () => {
    expect(checkCsrf(post('A'.repeat(42), TOKEN))).toBe(false);
    expect(checkCsrf(post(`${TOKEN}A`, TOKEN))).toBe(false);
  });

  it('fails when the cookie is missing', () => {
    expect(checkCsrf(post(TOKEN, null))).toBe(false);
  });

  it('reads the header by its name regardless of case', () => {
    const request = requestWithCookies(URL_, { [CSRF_COOKIE]: TOKEN }, {
      method: 'POST',
      headers: { 'x-csrf-token': TOKEN },
    });
    expect(checkCsrf(request)).toBe(true);
    expect(CSRF_HEADER).toBe('X-CSRF-Token');
  });

  it('compares with timingSafeEqual', () => {
    expect(checkCsrf(post(TOKEN, TOKEN))).toBe(true);
    expect(timingSafeEqual).toHaveBeenCalledTimes(1);
    checkCsrf(post('B'.repeat(43), TOKEN));
    expect(timingSafeEqual).toHaveBeenCalledTimes(2);
  });

  it('never calls the comparison with buffers of unequal length', () => {
    checkCsrf(post('short', TOKEN));
    for (const [a, b] of timingSafeEqual.mock.calls as [Buffer, Buffer][]) {
      expect(a.length).toBe(b.length);
    }
  });

  it('skips a cookie part that has no name=value form', () => {
    const request = new Request(URL_, {
      method: 'POST',
      headers: { Cookie: `junk; ${CSRF_COOKIE}=${TOKEN}=`, [CSRF_HEADER]: `${TOKEN}=` },
    });
    expect(checkCsrf(request)).toBe(true);
  });

  it('is not fooled by another cookie of similar name', () => {
    const request = requestWithCookies(URL_, { [`x${CSRF_COOKIE}`]: TOKEN }, {
      method: 'POST',
      headers: { [CSRF_HEADER]: TOKEN },
    });
    expect(checkCsrf(request)).toBe(false);
  });
});

describe('issueCsrf', () => {
  it('returns a random 32-byte base64url token and sets it as the cookie', async () => {
    const token = await issueCsrf();
    expect(token).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(Buffer.from(token, 'base64url')).toHaveLength(32);
    expect(lastWrite(CSRF_COOKIE)?.value).toBe(token);
  });

  it('gives a different token each time', async () => {
    expect(await issueCsrf()).not.toBe(await issueCsrf());
  });

  it('sets a cookie the page script can read, SameSite=Strict, Path=/, Secure', async () => {
    await issueCsrf();
    const options = lastWrite(CSRF_COOKIE)?.options ?? {};
    expect(options).toMatchObject({ sameSite: 'strict', path: '/', secure: true });
    expect(options.httpOnly).toBeFalsy();
  });

  it('is not Secure only in development', async () => {
    vi.stubEnv('NODE_ENV', 'development');
    await issueCsrf();
    expect(lastWrite(CSRF_COOKIE)?.options.secure).toBe(false);
  });

  it('takes its bytes from crypto.getRandomValues', async () => {
    const spy = vi.spyOn(crypto, 'getRandomValues').mockImplementation(((a: Uint8Array) => {
      a.fill(255);
      return a;
    }) as never);
    const token = await issueCsrf();
    expect(spy).toHaveBeenCalled();
    expect(token).toBe(Buffer.alloc(32, 255).toString('base64url'));
  });

  it('writes nothing to the console', async () => {
    const spy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    await issueCsrf();
    expect(spy).not.toHaveBeenCalled();
  });
});

describe('clearCsrf', () => {
  it('expires the cookie with the same attributes', async () => {
    await clearCsrf();
    const write = lastWrite(CSRF_COOKIE);
    expect(write?.value).toBe('');
    expect(write?.options).toMatchObject({
      maxAge: 0,
      sameSite: 'strict',
      path: '/',
      secure: true,
    });
  });
});
