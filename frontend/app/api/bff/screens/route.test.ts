// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER, csrfTokenFor } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { standInToken } from '@/test/fixtures/exchange';
import { pairingBackend, screenHandlers } from '@/test/msw/handlers/screens';
import { server } from '@/test/msw/server';
import { BACKEND_ROOT, SIGN_IN_HOST } from '@/test/oidc/constants';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// POST /api/bff/screens: a shift lead types the code shown on a wall display. Role lead, CSRF. The
// tenant is the lead's token's and nothing the page sends; the board a screen shows is always the
// organisation's own (the page offers no choice).

const URL_ = `https://${SIGN_IN_HOST}/api/bff/screens`;
// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = await csrfTokenFor({ tenantId: 'trust-a', host: SIGN_IN_HOST, sub: 'stf-1' }, 'N'.repeat(43));

// One token per role for the whole file: it carries an expiry in whole seconds, so two calls that straddle a
// second would give two different tokens and a test that compares them would fail on a slow machine.
const issued = new Map<string, string>();
function tokenFor(role: string) {
  const held = issued.get(role);
  if (held !== undefined) return held;
  const token = standInToken({ sub: `stf-${role}`, role, aud: 'diucs-api', exp: Math.floor(Date.now() / 1000) + 3600 });
  issued.set(role, token);
  return token;
}

async function lead(body: unknown, options: { role?: Role | null; csrf?: boolean; raw?: string } = {}) {
  const role = options.role === undefined ? 'lead' : options.role;
  const cookies: Record<string, string> = { [CSRF_COOKIE]: CSRF };
  if (role !== null) {
    cookies[SESSION_COOKIE] = await sealSession({
      role,
      tenantId: 'trust-a',
      host: SIGN_IN_HOST,
      services: [],
      sub: 'stf-1',
      backendToken: tokenFor(role),
      expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
    });
  }
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Host: SIGN_IN_HOST };
  if (options.csrf !== false) headers[CSRF_HEADER] = CSRF;
  return POST(requestWithCookies(URL_, cookies, { method: 'POST', headers, body: options.raw ?? JSON.stringify(body) }));
}

async function startPairing() {
  return pairingBackend.start(SIGN_IN_HOST);
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  pairingBackend.reset();
  server.use(...screenHandlers);
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/screens: who may', () => {
  it('is 401 with no session and 403 for every role but lead', async () => {
    await startPairing();
    expect((await lead({ code: '482913', name: 'Control room' }, { role: null })).status).toBe(401);
    for (const role of ['advisor', 'clinical', 'owner', 'exec', 'wall', 'reporter', 'support', 'audit'] as const) {
      expect((await lead({ code: '482913', name: 'Control room' }, { role })).status).toBe(403);
    }
    expect(pairingBackend.connects).toEqual([]);
  });

  it('is 403 without the CSRF header, and calls nothing', async () => {
    await startPairing();
    const response = await lead({ code: '482913', name: 'Control room' }, { csrf: false });
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ code: 'csrf' });
    expect(pairingBackend.connects).toEqual([]);
  });
});

describe('POST /api/bff/screens: connecting', () => {
  it('connects the screen and tells the page its name, that it is online and when', async () => {
    await startPairing();
    const response = await lead({ code: '482 913', name: ' Control room ', location: ' Ward 4 corridor ' });
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ name: 'Control room', status: 'online', connectedAt: expect.stringMatching(/^\d{4}-\d\d-\d\dT.*Z$/) });
    expect(response.headers.get('cache-control')).toBe('private, no-store');
  });

  it('sends the code without its space, the trimmed name and place, the lead’s own token and a fresh idempotency key', async () => {
    await startPairing();
    await lead({ code: '482 913', name: ' Control room ', location: ' Ward 4 corridor ' });
    const sent = pairingBackend.connects.at(-1)!;
    expect(sent.body).toEqual({ code: '482913', name: 'Control room', location: 'Ward 4 corridor' });
    expect(sent.authorization).toBe(`Bearer ${tokenFor('lead')}`);
    expect(sent.idempotencyKey).toMatch(/^[A-Za-z0-9-]{8,64}$/);
    await startPairing();
    await lead({ code: '271828', name: 'Control room' });
    expect(pairingBackend.connects.at(-1)!.idempotencyKey).not.toBe(sent.idempotencyKey);
  });

  it('refuses a connect that names a tenant or a scope with 400, and calls nothing (TEN-044)', async () => {
    await startPairing();
    for (const extra of [{ tenant: 'trust-b' }, { tenantId: 'trust-b' }, { scope: 'network' }, { network: 'net-x' }]) {
      expect((await lead({ code: '482913', name: 'Control room', ...extra })).status, JSON.stringify(extra)).toBe(400);
    }
    expect(pairingBackend.connects).toHaveLength(0);
  });

  it('forwards the fields of a connect and no others: a device id and a role are dropped', async () => {
    await startPairing();
    await lead({ code: '482913', name: 'Control room', deviceId: 'dev-9', role: 'wall' });
    expect(pairingBackend.connects.at(-1)!.body).toEqual({ code: '482913', name: 'Control room' });
  });

  it('is 404 for a code that is wrong, used or out of time, with the page’s message', async () => {
    await startPairing();
    pairingBackend.expire('pairing-1');
    const response = await lead({ code: '482913', name: 'Control room' });
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'That code is not valid or has expired. Check the screen for a new code.' });
  });

  it('passes a throttle on with its wait, and an outage as 503, in words of its own', async () => {
    pairingBackend.failWith = { status: 429, headers: { 'Retry-After': '600' } };
    await startPairing();
    pairingBackend.failWith = { status: 429, headers: { 'Retry-After': '600' } };
    const throttled = await lead({ code: '482913', name: 'Control room' });
    expect(throttled.status).toBe(429);
    expect(throttled.headers.get('retry-after')).toBe('600');
    expect(await throttled.json()).toMatchObject({ code: 'throttled', message: 'Too many attempts. Wait a few minutes and try again.' });
    pairingBackend.failWith = { status: 503 };
    expect((await lead({ code: '482913', name: 'Control room' })).status).toBe(503);
  });
});

describe('POST /api/bff/screens: what it refuses before the back end is asked', () => {
  it.each([
    ['no code', { name: 'Control room' }, 'code', 'Enter the code shown on the screen'],
    ['an empty code', { code: '  ', name: 'Control room' }, 'code', 'Enter the code shown on the screen'],
    ['a code of five digits', { code: '48291', name: 'Control room' }, 'code', 'The code has 6 numbers'],
    ['a code with letters', { code: '48291a', name: 'Control room' }, 'code', 'The code has 6 numbers'],
    ['a code that is a number', { code: 482913, name: 'Control room' }, 'code', 'Enter the code shown on the screen'],
    ['no name', { code: '482913' }, 'name', 'Enter a name for the screen'],
    ['an empty name', { code: '482913', name: ' ' }, 'name', 'Enter a name for the screen'],
    ['a name of 61 characters', { code: '482913', name: 'a'.repeat(61) }, 'name', 'Use 60 characters or fewer.'],
    ['a place of 61 characters', { code: '482913', name: 'Control room', location: 'a'.repeat(61) }, 'location', 'Use 60 characters or fewer.'],
    ['a place that is not text', { code: '482913', name: 'Control room', location: 7 }, 'location', 'Use 60 characters or fewer.'],
  ])('is 400 for %s, and names the field', async (_name, body, field, message) => {
    const response = await lead(body);
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ code: 'invalid', field, message });
    expect(pairingBackend.connects).toEqual([]);
  });

  it.each(['', 'not json', '[]', 'null', '7'])('is 400 for a body of %j', async (raw) => {
    const response = await lead(null, { raw });
    expect(response.status).toBe(400);
    expect(pairingBackend.connects).toEqual([]);
  });

  it('is 400 for a body over a kilobyte', async () => {
    const response = await lead({ code: '482913', name: 'a', location: 'b'.repeat(2000) });
    expect(response.status).toBe(400);
  });

  it('asks the page to check the name and place when the back end refuses them (it looks for patient information)', async () => {
    await startPairing();
    pairingBackend.failWith = null;
    const { http, HttpResponse } = await import('msw');
    server.use(http.post(`${BACKEND_ROOT}/screens`, () => HttpResponse.json({}, { status: 422 })));
    const response = await lead({ code: '482913', name: 'Control room' });
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({ code: 'invalid', field: 'name', message: 'Check the screen name and where it is. Do not include patient information.' });
  });

  it('shows no token, code or name in what it logs', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((l) => vi.spyOn(console, l).mockImplementation(() => {}));
    await startPairing();
    await lead({ code: '482913', name: 'Control room' });
    await lead({ code: '482913', name: 'Control room' });
    const logged = spies.flatMap((s) => s.mock.calls).join(' ');
    for (const secret of [tokenFor('lead'), '482913', 'Control room']) expect(logged).not.toContain(secret);
  });
});
