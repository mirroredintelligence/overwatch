// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { A, BACKEND, DEVICE } from '@/test/fixtures/reporter';
import { cookiesMock, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { answer, backendAnswers, phoneCall, resetSeenBackend, seenBackend } from '@/test/preSessionCalls';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// How the reporter wants to be contacted, before anyone is signed in (W33, W34, W37, W8E, DEC-813): the
// set-up channel step, and the locked PIN's "use text". The phone proves itself by a text code in the
// last ten minutes; the back end says no (403) for any device it cannot use.

const PATH = '/identity/channel';
const call = (body: unknown, options = {}) => phoneCall(POST, '/api/bff/identity/channel', body, options);

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeenBackend();
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/identity/channel', () => {
  it.each(['app', 'text', 'email'])('records %s for the phone’s device, addressed to the host, with no bearer', async (channel) => {
    answer(backendAnswers('post', PATH, 200, { channel }));
    const response = await call({ channel });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true, channel });
    expect(seenBackend).toEqual([{ method: 'POST', path: PATH, host: A.host, authorization: null, body: { deviceId: DEVICE, channel } }]);
  });

  it('answers a device that is not verified (403) as needing a code first, and a missing route not at all as built', async () => {
    answer(backendAnswers('post', PATH, 403, { resourceType: 'OperationOutcome' }));
    const response = await call({ channel: 'text' });
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ code: 'needs-code' });
  });

  it.each([
    ['a channel that is not one of the three', { channel: 'fax' }],
    ['no channel', {}],
    ['a channel that is not text', { channel: 3 }],
    ['a device', { channel: 'text', deviceId: 'E'.repeat(22) }],
    ['a number', { channel: 'text', phone: '07700900123' }],
    ['a tenant', { channel: 'text', tenant: 'trust-b' }],
  ])('refuses %s, 400, without calling the back end', async (_name, body) => {
    expect((await call(body)).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('refuses a write with no CSRF token of this phone, before the back end', async () => {
    expect((await call({ channel: 'text' }, { csrf: false })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });

  it('says 429 when limited, and 503 for anything else', async () => {
    answer(backendAnswers('post', PATH, 429, {}));
    expect((await call({ channel: 'text' })).status).toBe(429);
    for (const status of [404, 500]) {
      answer(backendAnswers('post', PATH, status, {}));
      expect((await call({ channel: 'text' })).status, `${status}`).toBe(503);
    }
  });

  it('does not answer a 200 that names no channel as done', async () => {
    answer(backendAnswers('post', PATH, 200, {}));
    expect((await call({ channel: 'text' })).status).toBe(503);
  });
});
