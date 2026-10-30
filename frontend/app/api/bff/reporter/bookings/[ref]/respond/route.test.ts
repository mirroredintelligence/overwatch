// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { cookiesMock, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const CSRF = 'C'.repeat(43);
const BACKEND = 'http://backend.test/fhir';

const session: Session = {
  role: 'reporter',
  services: ['svc-1'],
  sub: 'sess-1',
  backendToken: 'sess-1',
  expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND);
  resetCookieWrites();
  cookiesMock.mockClear();
});

async function call(body: string, withSession = true, key = 'key-abcdefgh') {
  const cookies: Record<string, string> = { [CSRF_COOKIE]: CSRF };
  if (withSession) cookies[SESSION_COOKIE] = await sealSession(session);
  return POST(
    requestWithCookies('https://app.test/api/bff/reporter/bookings/4821/respond', cookies, {
      method: 'POST',
      headers: { [CSRF_HEADER]: CSRF, 'Idempotency-Key': key },
      body,
    }),
    { params: Promise.resolve({ ref: '4821' }) },
  );
}

describe('POST /api/bff/reporter/bookings/[ref]/respond', () => {
  it('needs a reporter session', async () => {
    expect((await call('{"decision":"confirm"}', false)).status).toBe(401);
  });

  it('refuses a decision that is neither confirm nor decline, and a reason that is not one of the four', async () => {
    expect((await call('{"decision":"maybe"}')).status).toBe(400);
    expect((await call('{"decision":"decline","reason":"bored"}')).status).toBe(400);
  });

  it('sends the decision to the back end as Parameters, with the bearer and the Idempotency-Key, and passes on only the status', async () => {
    let seen: { auth: string | null; key: string | null; body: unknown } | undefined;
    server.use(
      http.post(/\/fhir\/Task\/[^/]+\/\$respond$/, async ({ request }) => {
        seen = { auth: request.headers.get('Authorization'), key: request.headers.get('Idempotency-Key'), body: await request.json() };
        return HttpResponse.json({ resourceType: 'Task', status: 'accepted', secret: 'do-not-pass' });
      }),
    );
    const response = await call('{"decision":"decline","reason":"full"}');
    expect(response.status).toBe(200);
    expect(await response.text()).not.toContain('do-not-pass');
    expect(seen?.auth).toBe('Bearer sess-1');
    expect(seen?.key).toBe('key-abcdefgh');
    expect(seen?.body).toEqual({
      resourceType: 'Parameters',
      parameter: [
        { name: 'decision', valueCode: 'decline' },
        { name: 'reason', valueCode: 'full' },
      ],
    });
  });
});
