// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { cookiesMock, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const CSRF = 'C'.repeat(43);
const URL_ = 'https://app.test/api/bff/identity/code/verify';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  resetCookieWrites();
  cookiesMock.mockClear();
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/identity/code/verify', () => {
  it('refuses a request without the csrf header', async () => {
    const response = await POST(
      requestWithCookies(URL_, { [CSRF_COOKIE]: CSRF }, { method: 'POST', body: '{"invite":"tok","code":"482913"}' }),
      { params: Promise.resolve({}) },
    );
    expect(response.status).toBe(403);
  });

  it('answers not-built (503) and takes no tenant or phone number from the body', async () => {
    const response = await POST(
      requestWithCookies(URL_, { [CSRF_COOKIE]: CSRF }, {
        method: 'POST',
        headers: { [CSRF_HEADER]: CSRF },
        body: '{"invite":"tok","code":"482913","tenant":"other","mobile":"07700900123"}',
      }),
      { params: Promise.resolve({}) },
    );
    expect(response.status).toBe(503);
    expect(await response.text()).not.toMatch(/07700|other/);
  });
});
