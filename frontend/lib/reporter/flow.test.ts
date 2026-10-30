// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { POST as pinVerify } from '@/app/api/bff/identity/pin/verify/route';
import { GET as start } from '@/app/api/bff/reporter/start/route';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { withBff } from '@/lib/bff/handler';
import { SESSION_COOKIE, unsealSession } from '@/lib/auth/session';
import { A, BACKEND, DEVICE, exchangeBody, exchangeHandler, PIN_SESSION, SIGNED_IN, type SeenExchange } from '@/test/fixtures/reporter';
import { DEVICE_COOKIE } from '@/lib/reporter/device';
import { cookiesMock, lastWrite, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { requestPreSession } from '@/test/requests';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// A reporter's whole session as the browser lives it (W8E): the PIN, the first write (which needs the
// session-bound CSRF token from the start route), the renewal half an hour later, and the end when
// the back end stops giving tokens. Each step is the real route and the real seam.

const T0 = new Date('2026-10-30T09:00:00Z');
const seen: SeenExchange[] = [];
let exchangeStatus = 200;
const bearers: (string | null)[] = [];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(T0);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
  seen.length = 0;
  bearers.length = 0;
  exchangeStatus = 200;
  server.use(
    http.post(`${BACKEND}/identity/pin/verify`, () => HttpResponse.json(SIGNED_IN)),
    exchangeHandler(seen, () => (exchangeStatus === 200 ? { body: exchangeBody({}, {}, new Date()) } : { status: exchangeStatus, body: {} })),
    http.post(`${BACKEND}/reporter/services/s1/report`, ({ request }) => {
      bearers.push(request.headers.get('authorization'));
      return HttpResponse.json({ result: 'recorded' });
    }),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

const write = withBff(
  async (_request, session) => {
    const { fhirFetch } = await import('@/lib/fhir/client');
    await fhirFetch('/reporter/services/s1/report', { method: 'POST', token: session.backendToken, root: true, body: { kind: 'confirm' } });
    return Response.json({ ok: true });
  },
  { roles: ['reporter'] },
);

async function signIn() {
  const response = await pinVerify(requestPreSession({ host: A.host, path: '/api/bff/identity/pin/verify', body: '{"pin":"123456"}' }), { params: Promise.resolve({}) });
  expect(response.status).toBe(200);
  return lastWrite(SESSION_COOKIE)?.value ?? '';
}

async function csrfFor(sessionCookie: string) {
  const response = await start(requestWithCookies(`https://${A.host}/api/bff/reporter/start`, { [DEVICE_COOKIE]: DEVICE, [SESSION_COOKIE]: sessionCookie }, { headers: { Host: A.host } }));
  return ((await response.json()) as { csrfToken: string }).csrfToken;
}

const writeRequest = (sessionCookie: string, csrf: string) =>
  requestWithCookies(`https://${A.host}/api/bff/reporter/services/s1/report`, { [SESSION_COOKIE]: sessionCookie, [CSRF_COOKIE]: csrf }, { method: 'POST', headers: { Host: A.host, [CSRF_HEADER]: csrf }, body: '{}' });

describe('a reporter’s session, from the PIN to its end', () => {
  it('a write after sign-in passes CSRF with the token the start route gives a signed-in phone, and carries the exchanged token', async () => {
    const cookie = await signIn();
    const csrf = await csrfFor(cookie);
    const response = await write(writeRequest(cookie, csrf), undefined);
    expect(response.status).toBe(200);
    const session = await unsealSession(cookie, T0);
    expect(bearers).toEqual([`Bearer ${session?.backendToken}`]);
    expect(bearers[0]).not.toContain(PIN_SESSION);
    expect(seen).toHaveLength(1);
  });

  it('a write with the phone’s pre-sign-in token is refused: the pre-session token never verifies for a session', async () => {
    const cookie = await signIn();
    const { preSessionCsrfFor } = await import('@/test/requests');
    const response = await write(writeRequest(cookie, preSessionCsrfFor(A.host)), undefined);
    expect(response.status).toBe(403);
    expect(bearers).toEqual([]);
  });

  it('twenty-six minutes later the next write renews the token, with the same CSRF token still good', async () => {
    const cookie = await signIn();
    const csrf = await csrfFor(cookie);
    vi.setSystemTime(new Date(T0.getTime() + 26 * 60_000));
    const response = await write(writeRequest(cookie, csrf), undefined);
    expect(response.status).toBe(200);
    expect(seen).toHaveLength(2);
    const renewed = await unsealSession(lastWrite(SESSION_COOKIE)?.value ?? '', new Date());
    expect(bearers).toEqual([`Bearer ${renewed?.backendToken}`]);
    expect(renewed?.expiresAt).toBe((await unsealSession(cookie, T0))?.expiresAt);
  });

  it('when the back end then stops giving tokens the session ends, and the write is never made', async () => {
    const cookie = await signIn();
    const csrf = await csrfFor(cookie);
    vi.setSystemTime(new Date(T0.getTime() + 26 * 60_000));
    exchangeStatus = 404;
    const response = await write(writeRequest(cookie, csrf), undefined);
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ code: 'session-ended' });
    expect(bearers).toEqual([]);
    expect(lastWrite(SESSION_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
  });

  it('after the session’s own eight hours it is no session at all, whatever the PIN session says', async () => {
    const cookie = await signIn();
    const csrf = await csrfFor(cookie);
    vi.setSystemTime(new Date(T0.getTime() + 8 * 3_600_000 + 1000));
    expect((await write(writeRequest(cookie, csrf), undefined)).status).toBe(401);
    expect(seen).toHaveLength(1);
  });
});
