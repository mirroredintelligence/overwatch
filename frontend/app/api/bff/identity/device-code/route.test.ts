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

// The text code of the 30-day check and of a PIN reset (W37, W8E, DEC-811, DEC-812). The phone has no
// session in either case, and no number in the browser: the back end finds the number through the
// device. The device is the phone's cookie, the purpose is one of two words, and the answer is 202.

const PATH = '/identity/device/code';
const call = (body: unknown, options = {}) => phoneCall(POST, '/api/bff/identity/device-code', body, options);

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeenBackend();
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/identity/device-code', () => {
  it.each(['reverify', 'pin-reset'])('asks for a %s code for this phone’s device, addressed to the host, with no bearer', async (purpose) => {
    answer(backendAnswers('post', PATH, 202, { accepted: true, resendAfterSeconds: 60 }));
    const response = await call({ purpose });
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ accepted: true, resendAfterSeconds: 60 });
    expect(seenBackend).toEqual([{ method: 'POST', path: PATH, host: A.host, authorization: null, body: { deviceId: DEVICE, purpose } }]);
  });

  it.each([
    ['a purpose that is not one of the two', { purpose: 'setup' }],
    ['the lost phone’s purpose', { purpose: 'new-device' }],
    ['no purpose', {}],
    ['a number', { purpose: 'reverify', phone: '07700900123' }],
    ['a device', { purpose: 'reverify', deviceId: 'E'.repeat(22) }],
    ['a tenant', { purpose: 'reverify', tenant: 'trust-b' }],
    ['text that is not JSON', 'purpose=reverify'],
  ])('refuses %s, 400, without calling the back end', async (_name, body) => {
    expect((await call(body)).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('refuses a write with no CSRF token of this phone, before the back end', async () => {
    expect((await call({ purpose: 'reverify' }, { csrf: false })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });

  it('says 429 with a retry time when limited, and 503 for anything but a 202', async () => {
    answer(backendAnswers('post', PATH, 429, {}, { 'Retry-After': '600' }));
    const limited = await call({ purpose: 'reverify' });
    expect(limited.status).toBe(429);
    expect(limited.headers.get('Retry-After')).toBe('600');
    for (const status of [404, 500, 200]) {
      answer(backendAnswers('post', PATH, status, {}));
      expect((await call({ purpose: 'reverify' })).status, `${status}`).toBe(503);
    }
  });

  it('is never stored and shows no device', async () => {
    answer(backendAnswers('post', PATH, 202, { accepted: true, resendAfterSeconds: 60 }));
    const response = await call({ purpose: 'reverify' });
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(await response.text()).not.toContain(DEVICE);
  });
});
