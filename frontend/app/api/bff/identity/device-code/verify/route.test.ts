// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { A, BACKEND, DEVICE } from '@/test/fixtures/reporter';
import { cookiesMock, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { answer, backendAnswers, newCodeNeeded, phoneCall, resetSeenBackend, seenBackend, wrongCode } from '@/test/preSessionCalls';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The check of the 30-day code and of the PIN-reset code (W37, W8E, DEC-812): a right code stamps the
// device, so the PIN routes that follow work. Same answers as the set-up code check.

const PATH = '/identity/device/code/verify';
const call = (body: unknown, options = {}) => phoneCall(POST, '/api/bff/identity/device-code/verify', body, options);

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeenBackend();
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/identity/device-code/verify', () => {
  it.each(['reverify', 'pin-reset'])('sends the %s code with the phone’s device id and answers ok', async (purpose) => {
    answer(backendAnswers('post', PATH, 200, { verified: true }));
    const response = await call({ purpose, code: '123456' });
    expect(await response.json()).toEqual({ ok: true });
    expect(seenBackend).toEqual([{ method: 'POST', path: PATH, host: A.host, authorization: null, body: { deviceId: DEVICE, purpose, code: '123456' } }]);
  });

  it('answers a wrong code with the tries left, and a lapsed or locked code as none left', async () => {
    answer(backendAnswers('post', PATH, 400, wrongCode(2)));
    expect(await (await call({ purpose: 'reverify', code: '123456' })).json()).toEqual({ ok: false, triesLeft: 2 });
    answer(backendAnswers('post', PATH, 400, newCodeNeeded(0)));
    expect(await (await call({ purpose: 'reverify', code: '123456' })).json()).toEqual({ ok: false, triesLeft: 0 });
  });

  it('answers a device that cannot take the code as 409 device-refused', async () => {
    answer(backendAnswers('post', PATH, 409, {}));
    const response = await call({ purpose: 'pin-reset', code: '123456' });
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ code: 'device-refused' });
  });

  it('says 429 when limited and 503 for anything else, never ok for a 200 that does not say verified', async () => {
    answer(backendAnswers('post', PATH, 429, {}));
    expect((await call({ purpose: 'reverify', code: '123456' })).status).toBe(429);
    for (const [status, body] of [[500, {}], [404, {}], [200, {}]] as const) {
      answer(backendAnswers('post', PATH, status, body));
      expect((await call({ purpose: 'reverify', code: '123456' })).status, `${status}`).toBe(503);
    }
  });

  it.each([
    ['a purpose of another kind', { purpose: 'setup', code: '123456' }],
    ['a code that is not six digits', { purpose: 'reverify', code: '12' }],
    ['no code', { purpose: 'reverify' }],
    ['a device', { purpose: 'reverify', code: '123456', deviceId: 'E'.repeat(22) }],
    ['a number', { purpose: 'reverify', code: '123456', phone: '07700900123' }],
  ])('refuses %s, 400, without calling the back end', async (_name, body) => {
    expect((await call(body)).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('refuses a write with no CSRF token of this phone, before the back end', async () => {
    expect((await call({ purpose: 'reverify', code: '123456' }, { csrf: false })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });
});
