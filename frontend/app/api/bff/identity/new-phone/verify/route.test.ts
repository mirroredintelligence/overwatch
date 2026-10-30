// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { cookiesMock, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const CSRF = 'C'.repeat(43);

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', 'http://backend.test/fhir');
  resetCookieWrites();
  cookiesMock.mockClear();
});

const call = () =>
  POST(
    requestWithCookies('https://app.test/api/bff/identity/new-phone/verify', { [CSRF_COOKIE]: CSRF }, {
      method: 'POST',
      headers: { [CSRF_HEADER]: CSRF },
      body: '{"phone":"07700900123","code":"482913"}',
    }),
    { params: Promise.resolve({}) },
  );

describe('POST /api/bff/identity/new-phone/verify', () => {
  it('answers pending-callback on success', async () => {
    server.use(http.post('http://backend.test/identity/new-phone/verify', () => HttpResponse.json({ status: 'pending-callback' })));
    const response = await call();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'pending-callback' });
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
});
