// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE } from '@/lib/auth/csrf';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { DEVICE_COOKIE } from '@/lib/reporter/device';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const URL_ = 'https://app.test/api/bff/reporter/start';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/reporter/start', () => {
  it('returns a csrf token and sets the csrf cookie to match it', async () => {
    const response = await GET(requestWithCookies(URL_, {}));
    const body = (await response.json()) as { csrfToken: string };
    expect(body.csrfToken).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(lastWrite(CSRF_COOKIE)?.value).toBe(body.csrfToken);
  });

  it('gives a new phone a device id in an http-only cookie, never in the body', async () => {
    const response = await GET(requestWithCookies(URL_, {}));
    const text = await response.text();
    const write = lastWrite(DEVICE_COOKIE);
    expect(write?.value).toMatch(/^[A-Za-z0-9_-]{22}$/);
    expect(write?.options).toMatchObject({ httpOnly: true, sameSite: 'strict' });
    expect(text).not.toContain(write?.value ?? 'no-device');
  });

  it('keeps the device it already has', async () => {
    await GET(requestWithCookies(URL_, { [DEVICE_COOKIE]: 'A'.repeat(22) }));
    expect(cookieWrites.filter((w) => w.name === DEVICE_COOKIE)).toHaveLength(0);
  });
});
