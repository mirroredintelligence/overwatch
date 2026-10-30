// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { cookiesMock, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { requestPreSession } from '@/test/requests';
import { TENANTS } from '@/test/tenants';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', 'http://backend.test/fhir');
  resetCookieWrites();
  cookiesMock.mockClear();
});

// A phone with no session: its CSRF token is bound to the host and its device id, and the call to the
// back end carries the host as the tenant and no bearer (the leak canary checks both).
const call = (options: { csrf?: boolean | string } = {}) =>
  POST(
    requestPreSession({
      host: TENANTS.A.host,
      path: '/api/bff/identity/new-phone/verify',
      body: '{"phone":"07700900123","code":"482913"}',
      ...options,
    }),
    { params: Promise.resolve({}) },
  );

describe('POST /api/bff/identity/new-phone/verify', () => {
  it('refuses a write with no CSRF token of this phone, and does not call the back end', async () => {
    let called = false;
    server.use(http.post('http://backend.test/identity/new-phone/verify', () => ((called = true), HttpResponse.json({}))));
    expect((await call({ csrf: false })).status).toBe(403);
    expect((await call({ csrf: 'C'.repeat(43) })).status).toBe(403);
    expect(called).toBe(false);
  });

  it('calls the back end for the host’s tenant, with no bearer and no tenant of its own', async () => {
    const seen: { host: string | null; auth: string | null; url: string }[] = [];
    server.use(
      http.post('http://backend.test/identity/new-phone/verify', ({ request }) => {
        seen.push({ host: request.headers.get('host'), auth: request.headers.get('authorization'), url: request.url });
        return HttpResponse.json({ status: 'pending-callback' });
      }),
    );
    await call();
    expect(seen).toEqual([{ host: TENANTS.A.host, auth: null, url: 'http://backend.test/identity/new-phone/verify' }]);
  });

  it('answers pending-callback on success', async () => {
    server.use(http.post('http://backend.test/identity/new-phone/verify', () => HttpResponse.json({ status: 'pending-callback' })));
    const response = await call();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'pending-callback', spoaPhone: null });
  });

  it('maps a wrong code to 400 wrong, a lapsed one to 410 expired, and too many tries to 429', async () => {
    server.use(
      http.post('http://backend.test/identity/new-phone/verify', () =>
        HttpResponse.json({ type: 'OperationOutcome', issue: [{ diagnostics: 'That code is not right' }] }, { status: 400 }),
      ),
    );
    expect((await call()).status).toBe(400);
    server.use(
      http.post('http://backend.test/identity/new-phone/verify', () =>
        HttpResponse.json({ type: 'OperationOutcome', issue: [{ diagnostics: 'Ask for a new code' }] }, { status: 400 }),
      ),
    );
    const expired = await call();
    expect(expired.status).toBe(410);
    expect(await expired.json()).toEqual({ code: 'expired' });
    server.use(http.post('http://backend.test/identity/new-phone/verify', () => HttpResponse.json({}, { status: 429 })));
    expect((await call()).status).toBe(429);
  });

  it('passes on the tenant’s coordination number when the back end gives one, and nothing else of the answer', async () => {
    server.use(http.post('http://backend.test/identity/new-phone/verify', () => HttpResponse.json({ status: 'pending-callback', spoaPhone: '01632 960001', person: 'prac-1' })));
    const body = (await (await call()).json()) as Record<string, unknown>;
    expect(body).toEqual({ status: 'pending-callback', spoaPhone: '01632 960001' });
  });
});
