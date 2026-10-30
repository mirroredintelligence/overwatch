// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { fhirFetch } from '@/lib/fhir/client';
import { SESSION_COOKIE, sealSession, unsealSession, type Session } from '@/lib/auth/session';
import { A, BACKEND, DEVICE, exchangeBody, exchangeHandler, iso, PERSON, PIN_SESSION, reporterToken, type SeenExchange } from '@/test/fixtures/reporter';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { csrfFor, requestAs } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { withBff } from './handler';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The reporter's token is renewed by the one seam every BFF route goes through (W8E, DEC-792), after
// the session, role, CSRF and tenant-input checks and before the handler, so a refused request never
// asks the back end for anything and a handler is only ever given a token that is good for the call.

const NOW = new Date('2026-10-30T09:00:00Z');
const seen: SeenExchange[] = [];
let reply: Parameters<typeof exchangeHandler>[1];
const URL_ = `https://${A.host}/api/bff/reporter/services`;

function reporter(tokenLeftMs: number, over: Partial<Session> = {}): Session {
  const expires = new Date(NOW.getTime() + tokenLeftMs);
  return {
    role: 'reporter',
    tenantId: A.id,
    host: A.host,
    services: ['s1'],
    sub: PERSON,
    device: DEVICE,
    backendToken: reporterToken({ exp: Math.floor(expires.getTime() / 1000) }, new Date(expires.getTime() - 30 * 60_000)),
    pinSession: PIN_SESSION,
    tokenExpiresAt: iso(expires),
    expiresAt: iso(new Date(NOW.getTime() + 6 * 3_600_000)),
    ...over,
  };
}

async function call(session: Session, method = 'GET', extra: { headers?: Record<string, string>; csrf?: boolean; url?: string } = {}) {
  const token = csrfFor(session);
  const cookies: Record<string, string> = { [SESSION_COOKIE]: await sealSession(session, NOW) };
  const headers = new Headers({ Host: A.host, ...extra.headers });
  if (extra.csrf !== false) {
    cookies[CSRF_COOKIE] = token;
    headers.set(CSRF_HEADER, token);
  }
  return requestWithCookies(extra.url ?? URL_, cookies, { method, headers });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
  seen.length = 0;
  reply = () => ({ body: exchangeBody({}, { services: ['s1'] }, new Date()) });
  server.use(exchangeHandler(seen, () => reply()));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

const echo = vi.fn((_request: Request, session: Session) => Response.json({ role: session.role, ok: true }));
beforeEach(() => echo.mockClear());

describe('withBff renews a reporter’s token', () => {
  it('gives the handler the new token when the old one has five minutes left, and rewrites the cookie', async () => {
    const before = reporter(4 * 60_000);
    const response = await withBff(echo)(await call(before), undefined);
    expect(response.status).toBe(200);
    const given = echo.mock.calls[0]?.[1] as Session;
    expect(given.backendToken).not.toBe(before.backendToken);
    expect(given).toMatchObject({ sub: PERSON, tenantId: A.id, host: A.host, pinSession: PIN_SESSION });
    expect(await unsealSession(lastWrite(SESSION_COOKIE)?.value ?? '', NOW)).toEqual(given);
  });

  it('leaves the answer as the handler made it: neither token reaches the browser', async () => {
    const before = reporter(4 * 60_000);
    const response = await withBff(echo)(await call(before), undefined);
    const text = await response.text();
    const given = echo.mock.calls[0]?.[1] as Session;
    for (const secret of [before.backendToken, given.backendToken, PIN_SESSION]) expect(text).not.toContain(secret);
    expect(response.headers.get('set-cookie')).toBeNull();
  });

  it('sends the back end the new token as the bearer, not the old one', async () => {
    let bearer: string | null = null;
    server.use(
      http.get(`${BACKEND}/reporter/services`, ({ request }) => {
        bearer = request.headers.get('authorization');
        return HttpResponse.json({ services: [] });
      }),
    );
    const before = reporter(60_000);
    const handler = withBff(async (_request, session) => {
      const { data } = await fhirFetch('/reporter/services', { token: session.backendToken, root: true });
      return Response.json(data);
    });
    expect((await handler(await call(before), undefined)).status).toBe(200);
    const given = (await unsealSession(lastWrite(SESSION_COOKIE)?.value ?? '', NOW))?.backendToken;
    expect(bearer).toBe(`Bearer ${given}`);
    expect(bearer).not.toContain(before.backendToken);
  });

  it('does not ask while the token has more than five minutes left', async () => {
    const before = reporter(20 * 60_000);
    await withBff(echo)(await call(before), undefined);
    expect(seen).toHaveLength(0);
    expect((echo.mock.calls[0]?.[1] as Session).backendToken).toBe(before.backendToken);
    expect(cookieWrites.filter((w) => w.name === SESSION_COOKIE)).toEqual([]);
  });

  it('renews for a POST too, after the CSRF check', async () => {
    const response = await withBff(echo)(await call(reporter(0), 'POST'), undefined);
    expect(response.status).toBe(200);
    expect(seen).toHaveLength(1);
  });

  it('renews a token that has already run out, from the live PIN session', async () => {
    const response = await withBff(echo)(await call(reporter(-40 * 60_000)), undefined);
    expect(response.status).toBe(200);
    expect(seen).toHaveLength(1);
  });

  it('never renews a session that has no PIN session (a staff session)', async () => {
    const staff = (await requestAs(A, 'lead', { path: '/api/bff/x' }));
    expect((await withBff(echo)(staff, undefined)).status).toBe(200);
    expect(seen).toHaveLength(0);
  });
});

describe('withBff ends a reporter’s session when the token cannot be renewed', () => {
  it('answers 401 session-ended, clears the session and the CSRF cookie, and never calls the handler, when the back end refuses', async () => {
    reply = () => ({ status: 404, body: {} });
    const response = await withBff(echo)(await call(reporter(0)), undefined);
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ code: 'session-ended' });
    expect(echo).not.toHaveBeenCalled();
    expect(lastWrite(SESSION_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
    expect(lastWrite(CSRF_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
  });

  it.each([
    ['another tenant', { tenant: 'trust-b' }],
    ['another person', { sub: 'prac-someone-else-0123456789abcdef0' }],
    ['another phone', { device: 'E'.repeat(22) }],
    ['a role that is not reporter', { role: 'lead' }],
  ])('ends it when the new token is for %s', async (_name, claims) => {
    reply = () => ({ body: exchangeBody({}, claims as never, new Date()) });
    const response = await withBff(echo)(await call(reporter(0)), undefined);
    expect(response.status).toBe(401);
    expect(echo).not.toHaveBeenCalled();
  });

  it('serves the call with the old token while it still lasts when the back end cannot be reached, and does not end the session', async () => {
    reply = () => 'network-error';
    const before = reporter(2 * 60_000);
    const response = await withBff(echo)(await call(before), undefined);
    expect(response.status).toBe(200);
    expect((echo.mock.calls[0]?.[1] as Session).backendToken).toBe(before.backendToken);
    expect(cookieWrites.filter((w) => w.name === SESSION_COOKIE)).toEqual([]);
  });

  it('ends the session when the token has run out and the back end cannot be reached', async () => {
    reply = () => 'network-error';
    const response = await withBff(echo)(await call(reporter(0)), undefined);
    expect(response.status).toBe(401);
    expect(echo).not.toHaveBeenCalled();
  });

  it('has the same 401 body as a request with no session', async () => {
    reply = () => ({ status: 404, body: {} });
    const ended = await withBff(echo)(await call(reporter(0)), undefined);
    expect(ended.headers.get('cache-control')).toContain('no-store');
  });
});

describe('withBff asks nothing of the back end for a request it refuses', () => {
  const due = () => reporter(0);

  it('no session: 401', async () => {
    const response = await withBff(echo)(new Request(URL_, { headers: { Host: A.host } }), undefined);
    expect(response.status).toBe(401);
    expect(seen).toHaveLength(0);
  });

  it('a role the route does not let in: 403', async () => {
    expect((await withBff(echo, { roles: ['lead'] })(await call(due()), undefined)).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('a write with no CSRF token: 403', async () => {
    expect((await withBff(echo)(await call(due(), 'POST', { csrf: false }), undefined)).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('a request that names a tenant: 400', async () => {
    expect((await withBff(echo)(await call(due(), 'GET', { url: `${URL_}?tenant=trust-b` }), undefined)).status).toBe(400);
    expect((await withBff(echo)(await call(due(), 'GET', { headers: { 'X-Tenant-Id': 'trust-b' } }), undefined)).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('a session of tenant A sent to tenant B’s host: 401', async () => {
    const request = await call(due(), 'GET', { headers: { Host: TENANTS.B.host } });
    expect((await withBff(echo)(request, undefined)).status).toBe(401);
    expect(seen).toHaveLength(0);
  });
});
