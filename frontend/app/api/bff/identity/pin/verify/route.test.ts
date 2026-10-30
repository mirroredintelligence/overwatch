// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, unsealSession } from '@/lib/auth/session';
import { cookieWrites, cookiesMock, lastWrite, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { requestPreSession, SAMPLE_DEVICE } from '@/test/requests';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The reporter's PIN sign-in (W34, W35). The session the BFF seals is for the tenant the back end
// answers with and the host the phone came to: an answer with no tenant, or a network id, signs nobody
// in. The back end's session id never reaches the browser.

const A = TENANTS.A;
const BACK_END = 'http://backend.test/identity/pin/verify';
const SIGNED_IN = { signedIn: true, sessionId: 'sess-sample-0001', role: 'reporter', services: ['s1'], tenant: A.id };

function answer(body: unknown, status = 200) {
  server.use(http.post(BACK_END, () => HttpResponse.json(body as Record<string, unknown>, { status })));
}
const call = (options: Parameters<typeof requestPreSession>[0] = {}) =>
  POST(requestPreSession({ host: A.host, path: '/api/bff/identity/pin/verify', body: '{"pin":"123456"}', ...options }), { params: Promise.resolve({}) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', 'http://backend.test/fhir');
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/identity/pin/verify', () => {
  it('seals a reporter session for the tenant the back end named and the host the phone came to, and answers ok only', async () => {
    answer(SIGNED_IN);
    const response = await call();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
    const write = lastWrite(SESSION_COOKIE);
    expect(write?.options).toMatchObject({ httpOnly: true, sameSite: 'strict' });
    expect(await unsealSession(write?.value ?? '')).toMatchObject({
      role: 'reporter',
      tenantId: A.id,
      host: A.host,
      services: ['s1'],
      device: SAMPLE_DEVICE,
      sub: 'sess-sample-0001',
    });
  });

  it('puts neither the session id nor the tenant in the answer the browser reads', async () => {
    answer(SIGNED_IN);
    const text = await (await call()).text();
    expect(text).not.toContain('sess-sample-0001');
    expect(text).not.toContain(A.id);
  });

  it.each([
    ['no tenant', undefined],
    ['a network id', 'net-sample'],
    ['a value that is not an id', 'Not A Tenant!'],
    ['a number', 7],
  ])('signs nobody in when the back end answers %s', async (_name, tenant) => {
    answer({ ...SIGNED_IN, tenant });
    const response = await call();
    expect(response.status).toBe(503);
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
    expect(cookieWrites.some((w) => w.name === SESSION_COOKIE)).toBe(false);
  });

  it('takes no tenant from the request: a body that names one is not sent on', async () => {
    let sent: unknown;
    server.use(
      http.post(BACK_END, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(SIGNED_IN);
      }),
    );
    await call({ body: '{"pin":"123456","tenant":"trust-b"}' });
    expect(sent).toEqual({ deviceId: SAMPLE_DEVICE, pin: '123456' });
  });

  it('refuses a write with no CSRF token of this phone, before the back end is called', async () => {
    let called = false;
    server.use(http.post(BACK_END, () => ((called = true), HttpResponse.json(SIGNED_IN))));
    expect((await call({ csrf: false })).status).toBe(403);
    expect(called).toBe(false);
  });

  it('answers a wrong PIN with the tries left, a locked one as locked, and one that needs a text code as reverify', async () => {
    answer({ triesLeft: 3 }, 403);
    expect(await (await call()).json()).toEqual({ ok: false, triesLeft: 3 });
    answer({}, 423);
    expect(await (await call()).json()).toEqual({ locked: true });
    answer({ needsTextCode: true }, 403);
    expect(await (await call()).json()).toEqual({ reverify: true });
    expect(lastWrite(SESSION_COOKIE)).toBeUndefined();
  });
});
