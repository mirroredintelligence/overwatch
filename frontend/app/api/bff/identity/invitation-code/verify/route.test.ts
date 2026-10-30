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

// The check of the set-up code (W33, W8E, DEC-811). The device is the phone's own cookie, never the body;
// a right code is recorded on the device by the back end in the same call. A wrong code says how many
// tries are left; five, or a lapsed code, say a new one is needed.

const TOKEN = 'SampleInvitationToken1';
const PATH = `/identity/invitations/${TOKEN}/code/verify`;
const call = (body: unknown, options = {}) => phoneCall(POST, '/api/bff/identity/invitation-code/verify', body, options);

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeenBackend();
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/identity/invitation-code/verify', () => {
  it('sends the code and the phone’s own device id, addressed to the host, and answers ok', async () => {
    answer(backendAnswers('post', PATH, 200, { verified: true }));
    const response = await call({ invite: TOKEN, code: '123456' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
    expect(seenBackend).toEqual([{ method: 'POST', path: PATH, host: A.host, authorization: null, body: { code: '123456', deviceId: DEVICE } }]);
  });

  it('refuses a body that names a device: the device is the cookie’s alone', async () => {
    expect((await call({ invite: TOKEN, code: '123456', deviceId: 'E'.repeat(22) })).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('answers a wrong code with the tries left', async () => {
    answer(backendAnswers('post', PATH, 400, wrongCode(3)));
    const response = await call({ invite: TOKEN, code: '123456' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: false, triesLeft: 3 });
  });

  it('answers five wrong tries, or a lapsed code, as no tries left', async () => {
    answer(backendAnswers('post', PATH, 400, newCodeNeeded(0)));
    expect(await (await call({ invite: TOKEN, code: '123456' })).json()).toEqual({ ok: false, triesLeft: 0 });
  });

  it('answers a 400 that names no tries as not ok, with no count', async () => {
    answer(backendAnswers('post', PATH, 400, { resourceType: 'OperationOutcome', issue: [{ code: 'invalid' }] }));
    expect(await (await call({ invite: TOKEN, code: '123456' })).json()).toEqual({ ok: false });
  });

  it('answers a right code that this phone cannot take as 409 device-refused', async () => {
    answer(backendAnswers('post', PATH, 409, { resourceType: 'OperationOutcome', issue: [{ code: 'conflict' }] }));
    const response = await call({ invite: TOKEN, code: '123456' });
    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({ code: 'device-refused' });
  });

  it('says 429 when the address is limited and 503 for anything else, and never says ok for a 200 that does not say verified', async () => {
    answer(backendAnswers('post', PATH, 429, {}));
    expect((await call({ invite: TOKEN, code: '123456' })).status).toBe(429);
    for (const [status, body] of [[500, {}], [404, {}], [200, {}], [200, { verified: false }]] as const) {
      answer(backendAnswers('post', PATH, status, body));
      expect((await call({ invite: TOKEN, code: '123456' })).status, `${status}`).toBe(503);
    }
  });

  it.each([
    ['a code that is not six digits', { invite: TOKEN, code: '12345' }],
    ['a code with letters', { invite: TOKEN, code: '12345a' }],
    ['a code that is a number', { invite: TOKEN, code: 123456 }],
    ['no invitation', { code: '123456' }],
    ['an invitation that cannot be one', { invite: 'bad token!', code: '123456' }],
    ['a tenant', { invite: TOKEN, code: '123456', tenant: 'trust-b' }],
    ['a number', { invite: TOKEN, code: '123456', phone: '07700900123' }],
  ])('refuses %s, 400, without calling the back end', async (_name, body) => {
    expect((await call(body)).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('refuses a write with no CSRF token of this phone, before the back end', async () => {
    expect((await call({ invite: TOKEN, code: '123456' }, { csrf: false })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });

  it('is never stored and shows neither the device, the token nor the code', async () => {
    answer(backendAnswers('post', PATH, 200, { verified: true }));
    const response = await call({ invite: TOKEN, code: '123456' });
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    const text = await response.text();
    for (const secret of [TOKEN, DEVICE, '123456']) expect(text).not.toContain(secret);
  });
});
