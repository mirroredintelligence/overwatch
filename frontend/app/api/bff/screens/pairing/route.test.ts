// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PAIRING_COOKIE } from '@/lib/screens/cookies';
import { lastWrite, requestWithCookies, resetCookieWrites, cookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { pairingBackend, screenHandlers } from '@/test/msw/handlers/screens';
import { server } from '@/test/msw/server';
import { BACKEND_ROOT, SIGN_IN_HOST } from '@/test/oidc/constants';
import { POST } from './route';
import { pairingFrom } from '@/lib/screens/cookies';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// POST /api/bff/screens/pairing: the wall display asks for a code. No session, no body, no input:
// the tenant is the host the display was opened on. The secret that proves the display is the one
// that asked stays in a sealed cookie and never reaches the page.

const URL_ = `https://${SIGN_IN_HOST}/api/bff/screens/pairing`;

function post(init: { headers?: Record<string, string>; body?: string; url?: string } = {}) {
  return POST(requestWithCookies(init.url ?? URL_, {}, { method: 'POST', headers: { Host: SIGN_IN_HOST, ...init.headers }, body: init.body }));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  pairingBackend.reset();
  server.use(...screenHandlers);
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/screens/pairing', () => {
  it('gives the page the code, the pairing id and when the code runs out, and nothing else', async () => {
    const response = await post();
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ pairingId: 'pairing-1', code: '482913', expiresAt: expect.stringMatching(/^\d{4}-\d\d-\d\dT/) });
    expect(response.headers.get('cache-control')).toBe('no-store');
  });

  it('keeps the secret in a sealed cookie, and out of the body, the headers and the address', async () => {
    const response = await post();
    const text = JSON.stringify([await response.clone().text(), [...response.headers.entries()]]);
    expect(text).not.toContain('screen-secret-1');
    const cookie = lastWrite(PAIRING_COOKIE)!;
    expect(cookie.value).not.toContain('screen-secret-1');
    const held = await pairingFrom(requestWithCookies(URL_, { [PAIRING_COOKIE]: cookie.value }));
    expect(held).toEqual({ pairingId: 'pairing-1', screenSecret: 'screen-secret-1' });
  });

  it('asks the back end for the host the display came to, and sends no body or header that names a tenant', async () => {
    await post({ headers: { 'X-Tenant-Id': 'trust-b', 'X-Forwarded-Host': 'trust-b.example.test' }, body: JSON.stringify({ tenant: 'trust-b', host: 'trust-b.example.test' }) });
    expect(pairingBackend.starts).toEqual([{ host: SIGN_IN_HOST }]);
  });

  it('reads nothing from the query string or the body', async () => {
    const response = await post({ url: `${URL_}?tenant=trust-b&code=000000`, body: '{"code":"000000"}' });
    expect(response.status).toBe(201);
    expect((await response.json()).code).toBe('482913');
  });

  it('replaces the earlier pairing, so a display that reloads holds one code at a time', async () => {
    await post();
    await post();
    const writes = cookieWrites.filter((w) => w.name === PAIRING_COOKIE);
    expect(writes).toHaveLength(2);
    expect(writes[0]!.value).not.toBe(writes[1]!.value);
  });

  it.each([
    [{ 'Sec-Fetch-Site': 'cross-site' }],
    [{ Origin: 'https://evil.example' }],
    [{ 'Sec-Fetch-Site': 'same-site' }],
  ])('refuses a request that did not come from this site’s own page (%j), and asks the back end for nothing', async (headers) => {
    const response = await post({ headers });
    expect(response.status).toBe(403);
    expect(pairingBackend.starts).toEqual([]);
    expect(lastWrite(PAIRING_COOKIE)).toBeUndefined();
  });

  it('answers 404 with no cookie for a host no tenant owns', async () => {
    const response = await post({ headers: { Host: 'unknown.example.test' } });
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
    expect(lastWrite(PAIRING_COOKIE)).toBeUndefined();
  });

  it('passes a throttle on with its wait, and a failure of the back end as unavailable, setting no cookie', async () => {
    pairingBackend.failWith = { status: 429, headers: { 'Retry-After': '600' } };
    const throttled = await post();
    expect(throttled.status).toBe(429);
    expect(throttled.headers.get('retry-after')).toBe('600');
    expect(await throttled.json()).toMatchObject({ code: 'throttled', message: 'Too many attempts. Wait a few minutes and try again.' });
    pairingBackend.failWith = { status: 503 };
    const down = await post();
    expect(down.status).toBe(503);
    expect(await down.json()).toMatchObject({ code: 'unavailable', message: 'Pairing is not available right now. Try again shortly.' });
    expect(lastWrite(PAIRING_COOKIE)).toBeUndefined();
  });

  it('says nothing the back end said', async () => {
    pairingBackend.failWith = { status: 503 };
    const response = await post();
    expect(JSON.stringify(await response.json())).not.toMatch(/Try again\.|transient|OperationOutcome/);
  });

  it('does not log the code, the pairing id or the secret', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((l) => vi.spyOn(console, l).mockImplementation(() => {}));
    await post();
    pairingBackend.failWith = { status: 503 };
    await post();
    const logged = spies.flatMap((s) => s.mock.calls).join(' ');
    for (const secret of ['482913', 'pairing-1', 'screen-secret-1']) expect(logged).not.toContain(secret);
  });
});
