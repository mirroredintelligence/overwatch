// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, verifyCsrfToken } from '@/lib/auth/csrf';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { DEVICE_COOKIE } from '@/lib/reporter/device';
import { preSessionSubject } from '@/lib/reporter/bff';
import { preSessionCsrfFor, SAMPLE_DEVICE } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { SESSION_COOKIE, sealSession } from '@/lib/auth/session';
import { csrfFor, sessionFor } from '@/test/requests';
import { DEVICE, iso, PERSON, PIN_SESSION, reporterToken } from '@/test/fixtures/reporter';
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

// A signed-in reporter's writes are checked against the session (TEN-046), so the token this route
// gives a signed-in phone is bound to the session, not to the phone: the pre-session token of a phone
// never verifies for a session (W8E: the reporter's in-app writes could not otherwise pass CSRF).
describe('GET /api/bff/reporter/start for a phone that is signed in', () => {
  const reporterSession = () =>
    sessionFor(A, 'reporter', {
      sub: PERSON,
      device: DEVICE,
      services: ['s1'],
      backendToken: reporterToken(),
      pinSession: PIN_SESSION,
      tokenExpiresAt: iso(new Date(Date.now() + 1_800_000)),
    });
  const asReporter = async (cookies: Record<string, string> = {}, session = reporterSession()) =>
    get({ [DEVICE_COOKIE]: DEVICE, [SESSION_COOKIE]: await sealSession(session), ...cookies });

  it('gives a token bound to the session: the one a withBff write of this reporter checks', async () => {
    const session = reporterSession();
    const response = await GET(await asReporter({}, session));
    const { csrfToken } = (await response.json()) as { csrfToken: string };
    expect(verifyCsrfToken(session, csrfToken)).toBe(true);
    expect(verifyCsrfToken(preSessionSubject(A.host, DEVICE), csrfToken)).toBe(false);
    expect(lastWrite(CSRF_COOKIE)?.value).toBe(csrfToken);
  });

  it('keeps the token the phone already holds when it is the session’s own, so two tabs agree', async () => {
    const session = reporterSession();
    const own = csrfFor(session);
    const response = await GET(await asReporter({ [CSRF_COOKIE]: own }, session));
    expect(((await response.json()) as { csrfToken: string }).csrfToken).toBe(own);
    expect(cookieWrites.filter((w) => w.name === CSRF_COOKIE)).toHaveLength(0);
  });

  it('replaces the phone’s pre-session token once there is a session', async () => {
    const response = await GET(await asReporter({ [CSRF_COOKIE]: preSessionCsrfFor(A.host) }));
    const { csrfToken } = (await response.json()) as { csrfToken: string };
    expect(csrfToken).not.toBe(preSessionCsrfFor(A.host));
    expect(verifyCsrfToken(reporterSession(), csrfToken)).toBe(true);
  });

  it('gives a pre-session token to a phone whose session is another host’s, expired, or not a reporter’s', async () => {
    const other = await sealSession(sessionFor(TENANTS.B, 'reporter', { device: DEVICE, backendToken: reporterToken(), pinSession: PIN_SESSION, tokenExpiresAt: iso(new Date(Date.now() + 1_800_000)) }));
    const staff = await sealSession(sessionFor(A, 'lead'));
    for (const cookie of [other, staff, 'not-a-session']) {
      resetCookieWrites();
      const { csrfToken } = (await (await GET(get({ [DEVICE_COOKIE]: DEVICE, [SESSION_COOKIE]: cookie }))).json()) as { csrfToken: string };
      expect(verifyCsrfToken(preSessionSubject(A.host, DEVICE), csrfToken)).toBe(true);
    }
  });

  it('puts neither the token of the session nor the PIN session in the answer', async () => {
    const session = reporterSession();
    const text = await (await GET(await asReporter({}, session))).text();
    for (const secret of [session.backendToken, PIN_SESSION, PERSON, A.id]) expect(text).not.toContain(secret);
  });
});
