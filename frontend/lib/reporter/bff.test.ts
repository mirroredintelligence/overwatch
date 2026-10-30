// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { cookiesMock, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { preSessionCsrfFor, requestPreSession, SAMPLE_DEVICE } from '@/test/requests';
import { sessionFor, csrfFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { preSession, preSessionSubject, preSessionSubjectOf } from './bff';
import { DEVICE_COOKIE } from './device';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const A = TENANTS.A;
const B = TENANTS.B;
const ok = preSession(() => Response.json({ done: true }));

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  resetCookieWrites();
  cookiesMock.mockClear();
});
afterEach(() => vi.unstubAllEnvs());

describe('preSession (a route for a phone with no session)', () => {
  it('lets a write through when the CSRF token is the one issued to this phone on this host', async () => {
    const response = await ok(requestPreSession({ host: A.host }), undefined);
    expect(response.status).toBe(200);
  });

  it('refuses a write with no CSRF header, a header that differs from the cookie, or no token at all', async () => {
    for (const csrf of [false, 'x'.repeat(87)] as const) {
      const response = await ok(requestPreSession({ host: A.host, csrf }), undefined);
      expect(response.status, String(csrf)).toBe(403);
    }
    const token = preSessionCsrfFor(A.host);
    const mismatched = requestWithCookies(`https://${A.host}/x`, { [DEVICE_COOKIE]: SAMPLE_DEVICE, [CSRF_COOKIE]: token }, {
      method: 'POST',
      headers: { Host: A.host, [CSRF_HEADER]: preSessionCsrfFor(A.host, 'E'.repeat(22)) },
    });
    expect((await ok(mismatched, undefined)).status).toBe(403);
  });

  it('refuses a token that was issued for another host, for another phone, or for a signed-in session', async () => {
    const other = preSessionCsrfFor(B.host);
    expect((await ok(requestPreSession({ host: A.host, csrf: other }), undefined)).status).toBe(403);
    const otherPhone = preSessionCsrfFor(A.host, 'E'.repeat(22));
    expect((await ok(requestPreSession({ host: A.host, csrf: otherPhone }), undefined)).status).toBe(403);
    const sessionToken = csrfFor(sessionFor(A, 'reporter'));
    expect((await ok(requestPreSession({ host: A.host, csrf: sessionToken }), undefined)).status).toBe(403);
  });

  it('refuses a write from a phone that has no device id yet (it has not been to reporter/start)', async () => {
    const token = preSessionCsrfFor(A.host);
    const request = requestWithCookies(`https://${A.host}/x`, { [CSRF_COOKIE]: token }, {
      method: 'POST',
      headers: { Host: A.host, [CSRF_HEADER]: token },
    });
    expect((await ok(request, undefined)).status).toBe(403);
  });

  it('does not ask for CSRF on a read', async () => {
    const response = await ok(requestPreSession({ host: A.host, method: 'GET', csrf: false }), undefined);
    expect(response.status).toBe(200);
  });

  it('answers a failure with the fixed-message response, naming nothing', async () => {
    const boom = preSession(() => {
      throw new Error('secret detail 07700900123');
    });
    const response = await boom(requestPreSession({ host: A.host }), undefined);
    expect(response.status).toBeGreaterThanOrEqual(500);
    expect(await response.text()).not.toContain('07700900123');
  });
});

describe('the subject of a phone’s CSRF token', () => {
  it('has no tenant (the back end knows it from the host), the host and the device', () => {
    expect(preSessionSubject(A.host, SAMPLE_DEVICE)).toEqual({ tenantId: '', host: A.host, sub: `device:${SAMPLE_DEVICE}` });
  });

  it('is null for a request with no device cookie', () => {
    expect(preSessionSubjectOf(new Request(`https://${A.host}/x`, { headers: { Host: A.host } }))).toBeNull();
    expect(preSessionSubjectOf(requestPreSession({ host: A.host }))).toEqual(preSessionSubject(A.host, SAMPLE_DEVICE));
  });
});
