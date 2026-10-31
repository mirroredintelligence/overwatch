// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import {
  cookieWrites,
  cookiesMock,
  lastWrite,
  requestWithCookies,
  resetCookieWrites,
  TEST_SESSION_SECRET,
} from '@/test/cookies';
import { csrfFor, sessionFor } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { DELETE, GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const BACKEND_TOKEN = 'backend-token-sample-value';
const URL_ = `https://${TENANTS.A.host}/api/bff/session`;
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);

const session: Session = sessionFor(TENANTS.A, 'advisor', {
  services: ['svc-1', 'svc-2'],
  sub: 'user-1',
  device: 'dev-1',
  backendToken: BACKEND_TOKEN,
});
// The CSRF token the session was issued: bound to its person, tenant, host and expiry.
const TOKEN = await csrfFor(session);

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

describe('GET /api/bff/session', () => {
  it('returns 200 with role, services and a csrfToken only: no backendToken, no sub, no tenant id', async () => {
    const cookie = await sealSession(session);
    const response = await GET(requestWithCookies(URL_, { [SESSION_COOKIE]: cookie }));
    expect(response.status).toBe(200);
    const text = await response.text();
    const body = JSON.parse(text);
    expect(body).toEqual({
      role: 'advisor',
      services: ['svc-1', 'svc-2'],
      csrfToken: expect.stringMatching(/^[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}$/),
    });
    expect(text).not.toContain(BACKEND_TOKEN);
    expect(text).not.toContain('backendToken');
    expect(text).not.toContain('device');
    expect(text).not.toContain('expiresAt');
    expect(text).not.toContain('user-1');
    expect(text).not.toContain(TENANTS.A.id);
    expect(text).not.toContain(TENANTS.A.host);
    expect(text).not.toMatch(/tenant/i);
  });

  it('issues the csrf cookie that matches the token it returns', async () => {
    const cookie = await sealSession(session);
    const response = await GET(requestWithCookies(URL_, { [SESSION_COOKIE]: cookie }));
    const body = await response.json();
    expect(lastWrite(CSRF_COOKIE)?.value).toBe(body.csrfToken);
  });

  it('reuses the csrf token already in the cookie instead of rotating it', async () => {
    const cookie = await sealSession(session);
    const response = await GET(
      requestWithCookies(URL_, { [SESSION_COOKIE]: cookie, [CSRF_COOKIE]: TOKEN }),
    );
    expect((await response.json()).csrfToken).toBe(TOKEN);
    expect(cookieWrites.filter((w) => w.name === CSRF_COOKIE)).toHaveLength(0);
  });

  it('replaces a csrf cookie that is not a token of this session: too short, the old unbound shape, or another tenant’s', async () => {
    const cookie = await sealSession(session);
    const other = await csrfFor(sessionFor(TENANTS.B, 'advisor', { sub: session.sub, host: session.host }));
    for (const stale of ['short', 'A'.repeat(43), other]) {
      resetCookieWrites();
      const response = await GET(requestWithCookies(URL_, { [SESSION_COOKIE]: cookie, [CSRF_COOKIE]: stale }));
      const body = await response.json();
      expect(body.csrfToken).not.toBe(stale);
      expect(body.csrfToken).toMatch(/^[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}$/);
      expect(lastWrite(CSRF_COOKIE)?.value).toBe(body.csrfToken);
    }
  });

  it('returns a csrf token that the checks accept for this session and refuse for another tenant’s', async () => {
    const cookie = await sealSession(session);
    const body = await (await GET(requestWithCookies(URL_, { [SESSION_COOKIE]: cookie }))).json();
    const { verifyCsrfToken } = await import('@/lib/auth/csrf');
    expect(await verifyCsrfToken(session, body.csrfToken)).toBe(true);
    expect(await verifyCsrfToken(sessionFor(TENANTS.B, 'advisor', { sub: session.sub, host: session.host }), body.csrfToken)).toBe(false);
  });

  it('returns 401 no-session with no cookie, and sets no cookie', async () => {
    const response = await GET(new Request(URL_));
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ code: 'no-session' });
    expect(cookieWrites).toHaveLength(0);
  });

  it('returns 401 no-session for a tampered or expired cookie', async () => {
    const good = await sealSession(session);
    const bad = `${good.slice(0, -2)}${good.endsWith('AA') ? 'BB' : 'AA'}`;
    const tampered = await GET(requestWithCookies(URL_, { [SESSION_COOKIE]: bad }));
    expect(tampered.status).toBe(401);
    const old = await sealSession(
      { ...session, expiresAt: '2026-10-23T13:30:00.000Z' },
      new Date('2026-10-23T13:12:00.000Z'),
    );
    const expired = await GET(requestWithCookies(URL_, { [SESSION_COOKIE]: old }));
    expect(expired.status).toBe(401);
    expect(await expired.json()).toEqual({ code: 'no-session' });
  });

  it('sets Cache-Control: private, no-store and varies by cookie and host, on every answer', async () => {
    const cookie = await sealSession(session);
    const ok = await GET(requestWithCookies(URL_, { [SESSION_COOKIE]: cookie }));
    expect(ok.headers.get('Cache-Control')).toBe('private, no-store');
    expect(ok.headers.get('Vary')).toMatch(/Cookie/i);
    expect(ok.headers.get('Vary')).toMatch(/Host/i);
    const none = await GET(new Request(URL_));
    expect(none.headers.get('Cache-Control')).toBe('private, no-store');
  });

  it('shows another tenant host no session at all, though the cookie was sent there', async () => {
    const cookie = await sealSession(session);
    const other = `https://${TENANTS.B.host}/api/bff/session`;
    const response = await GET(requestWithCookies(other, { [SESSION_COOKIE]: cookie }));
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ code: 'no-session' });
  });

  it('refuses a request that names a tenant', async () => {
    const cookie = await sealSession(session);
    const response = await GET(requestWithCookies(`${URL_}?tenant=${TENANTS.B.id}`, { [SESSION_COOKIE]: cookie }));
    expect(response.status).toBe(400);
  });

  it('writes nothing to the console', async () => {
    const spies = (['log', 'info', 'warn', 'error'] as const).map((m) =>
      vi.spyOn(console, m).mockImplementation(() => undefined),
    );
    const cookie = await sealSession(session);
    await GET(requestWithCookies(URL_, { [SESSION_COOKIE]: cookie }));
    await GET(new Request(URL_));
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });
});

describe('DELETE /api/bff/session', () => {
  it('tells the browser to clear its caches and storage, so a service worker or stored value cannot outlive the session (TEN-050)', async () => {
    const response = await del('ok');
    expect(response.headers.get('Clear-Site-Data')).toBe('"cache", "storage"');
  });

  it('does not send Clear-Site-Data when the request was refused (no CSRF, no session)', async () => {
    expect((await del('none')).headers.get('Clear-Site-Data')).toBeNull();
    const none = await DELETE(requestWithCookies(URL_, { [CSRF_COOKIE]: TOKEN }, { method: 'DELETE', headers: { [CSRF_HEADER]: TOKEN } }));
    expect(none.headers.get('Clear-Site-Data')).toBeNull();
  });

  it('never sends Clear-Site-Data on a read of the session', async () => {
    const cookie = await sealSession(session);
    const response = await GET(requestWithCookies(URL_, { [SESSION_COOKIE]: cookie }));
    expect(response.headers.get('Clear-Site-Data')).toBeNull();
  });

  it('has no-store on the 204 too', async () => {
    const cookie = await sealSession(session);
    const response = await DELETE(
      requestWithCookies(URL_, { [SESSION_COOKIE]: cookie, [CSRF_COOKIE]: TOKEN }, { method: 'DELETE', headers: { [CSRF_HEADER]: TOKEN } }),
    );
    expect(response.headers.get('Cache-Control')).toBe('private, no-store');
  });

  async function del(csrf: 'ok' | 'none') {
    const cookie = await sealSession(session);
    const headers = new Headers();
    if (csrf === 'ok') headers.set(CSRF_HEADER, TOKEN);
    return DELETE(
      requestWithCookies(
        URL_,
        { [SESSION_COOKIE]: cookie, [CSRF_COOKIE]: TOKEN },
        { method: 'DELETE', headers },
      ),
    );
  }

  it('returns 204 and clears both cookies with Max-Age 0', async () => {
    const response = await del('ok');
    expect(response.status).toBe(204);
    expect(await response.text()).toBe('');
    for (const name of [SESSION_COOKIE, CSRF_COOKIE]) {
      const write = lastWrite(name);
      expect(write?.value).toBe('');
      expect(write?.options.maxAge).toBe(0);
      expect(write?.options.path).toBe('/');
    }
  });

  it('returns 403 csrf without the header and clears nothing', async () => {
    const response = await del('none');
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ code: 'csrf' });
    expect(cookieWrites).toHaveLength(0);
  });

  it('returns 401 no-session when there is no session', async () => {
    const response = await DELETE(
      requestWithCookies(URL_, { [CSRF_COOKIE]: TOKEN }, { method: 'DELETE', headers: { [CSRF_HEADER]: TOKEN } }),
    );
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ code: 'no-session' });
  });
});
