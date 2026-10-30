// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, verifyCsrfToken } from '@/lib/auth/csrf';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { DEVICE_COOKIE } from '@/lib/reporter/device';
import { preSessionSubject } from '@/lib/reporter/bff';
import { preSessionCsrfFor, SAMPLE_DEVICE } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const A = TENANTS.A;
const URL_ = `https://${A.host}/api/bff/reporter/start`;

function get(cookies: Record<string, string> = {}, host: string = A.host) {
  return requestWithCookies(URL_.replace(A.host, host), cookies, { headers: { Host: host } });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/reporter/start', () => {
  it('returns a csrf token bound to this host and this phone, and sets the csrf cookie to match it', async () => {
    const response = await GET(get());
    const body = (await response.json()) as { csrfToken: string };
    expect(body.csrfToken).toMatch(/^[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}$/);
    expect(lastWrite(CSRF_COOKIE)?.value).toBe(body.csrfToken);
    const device = lastWrite(DEVICE_COOKIE)?.value ?? '';
    expect(verifyCsrfToken(preSessionSubject(A.host, device), body.csrfToken)).toBe(true);
    expect(verifyCsrfToken(preSessionSubject(TENANTS.B.host, device), body.csrfToken)).toBe(false);
  });

  it('keeps the token the phone already holds when it is its own, so two tabs agree', async () => {
    const own = preSessionCsrfFor(A.host);
    const response = await GET(get({ [DEVICE_COOKIE]: SAMPLE_DEVICE, [CSRF_COOKIE]: own }));
    expect(((await response.json()) as { csrfToken: string }).csrfToken).toBe(own);
    expect(cookieWrites.filter((w) => w.name === CSRF_COOKIE)).toHaveLength(0);
  });

  it('replaces a token that was made for another host or another phone', async () => {
    for (const planted of [preSessionCsrfFor(TENANTS.B.host), preSessionCsrfFor(A.host, 'E'.repeat(22)), 'C'.repeat(43)]) {
      resetCookieWrites();
      const response = await GET(get({ [DEVICE_COOKIE]: SAMPLE_DEVICE, [CSRF_COOKIE]: planted }));
      const { csrfToken } = (await response.json()) as { csrfToken: string };
      expect(csrfToken).not.toBe(planted);
      expect(verifyCsrfToken(preSessionSubject(A.host, SAMPLE_DEVICE), csrfToken)).toBe(true);
    }
  });

  it('gives a new phone a device id in an http-only cookie, never in the body', async () => {
    const response = await GET(get());
    const text = await response.text();
    const write = lastWrite(DEVICE_COOKIE);
    expect(write?.value).toMatch(/^[A-Za-z0-9_-]{22}$/);
    expect(write?.options).toMatchObject({ httpOnly: true, sameSite: 'strict' });
    expect(text).not.toContain(write?.value ?? 'no-device');
    expect(text).not.toContain(A.id);
  });

  it('keeps the device it already has', async () => {
    await GET(get({ [DEVICE_COOKIE]: 'A'.repeat(22) }));
    expect(cookieWrites.filter((w) => w.name === DEVICE_COOKIE)).toHaveLength(0);
  });

  it('is never stored', async () => {
    const response = await GET(get());
    expect(response.headers.get('cache-control')).toContain('no-store');
  });
});
