// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE } from '@/lib/auth/csrf';
import { SESSION_COOKIE, type Session } from '@/lib/auth/session';
import { A, BACKEND, DEVICE, iso, PERSON, PIN_SESSION, reporterToken } from '@/test/fixtures/reporter';
import { cookieWrites, cookiesMock, lastWrite, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { requestAs } from '@/test/requests';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// Sign out of every phone (W55, W8E). The back end's route (R13) ends every session of the signed-in
// person and revokes their devices; it takes the reporter's token like any other call. This phone's own
// session ends with it, here, not only when the page remembers to ask.

const SIGN_OUT = `${BACKEND}/identity/sign-out-everywhere`;
const reporter: Partial<Session> = {
  sub: PERSON,
  device: DEVICE,
  services: ['s1'],
  backendToken: reporterToken(),
  pinSession: PIN_SESSION,
  tokenExpiresAt: iso(new Date(Date.now() + 1_800_000)),
};
const call = async (role: 'reporter' | 'lead' = 'reporter', options: Parameters<typeof requestAs>[2] = {}) =>
  POST(await requestAs(A, role, { method: 'POST', path: '/api/bff/identity/sign-out-everywhere', csrf: true, session: reporter, body: '{}', ...options }), { params: Promise.resolve({}) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/identity/sign-out-everywhere', () => {
  it('calls the back end with the reporter’s token (never the PIN session) and a key, and answers how many phones were signed out', async () => {
    let seen: { authorization: string | null; key: string | null } | undefined;
    server.use(
      http.post(SIGN_OUT, ({ request }) => {
        seen = { authorization: request.headers.get('authorization'), key: request.headers.get('idempotency-key') };
        return HttpResponse.json({ signedOut: 3 });
      }),
    );
    const response = await call();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ signedOut: 3 });
    expect(seen?.authorization).toBe(`Bearer ${reporter.backendToken}`);
    expect(seen?.authorization).not.toContain(PIN_SESSION);
    expect(seen?.key).toMatch(/^[A-Za-z0-9-]{8,64}$/);
  });

  it('ends this phone’s own session at once: the session cookie and the CSRF cookie are cleared', async () => {
    server.use(http.post(SIGN_OUT, () => HttpResponse.json({ signedOut: 1 })));
    await call();
    expect(lastWrite(SESSION_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
    expect(lastWrite(CSRF_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
  });

  it('answers 0 for a count that is not a number', async () => {
    server.use(http.post(SIGN_OUT, () => HttpResponse.json({ signedOut: 'many' })));
    expect(await (await call()).json()).toEqual({ signedOut: 0 });
  });

  it('does not end this phone’s session when the back end failed', async () => {
    server.use(http.post(SIGN_OUT, () => HttpResponse.json({}, { status: 500 })));
    const response = await call();
    expect(response.status).toBe(500);
    expect(cookieWrites.filter((w) => w.name === SESSION_COOKIE)).toEqual([]);
  });

  it('answers 401 session-ended, and clears the session, when the back end no longer knows the token', async () => {
    server.use(http.post(SIGN_OUT, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ code: 'login' }] }, { status: 401 })));
    const response = await call();
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({ code: 'session-ended' });
    expect(lastWrite(SESSION_COOKIE)).toMatchObject({ value: '', options: { maxAge: 0 } });
  });

  it('does not answer not-built any more', async () => {
    server.use(http.post(SIGN_OUT, () => HttpResponse.json({ signedOut: 0 })));
    expect(await (await call()).text()).not.toContain('not-built');
  });

  it('is for a reporter: another role is refused before the back end is called', async () => {
    let called = false;
    server.use(http.post(SIGN_OUT, () => ((called = true), HttpResponse.json({ signedOut: 1 }))));
    expect((await call('lead')).status).toBe(403);
    expect(called).toBe(false);
  });

  it('refuses a write with no CSRF token, before the back end is called', async () => {
    let called = false;
    server.use(http.post(SIGN_OUT, () => ((called = true), HttpResponse.json({ signedOut: 1 }))));
    expect((await call('reporter', { csrf: undefined })).status).toBe(403);
    expect(called).toBe(false);
  });

  it('asks for no tenant: a body or a query that names one is refused', async () => {
    expect((await call('reporter', { path: '/api/bff/identity/sign-out-everywhere?tenant=trust-b' })).status).toBe(400);
  });
});
