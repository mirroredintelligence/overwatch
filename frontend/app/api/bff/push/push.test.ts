// @vitest-environment node
import { createHash } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { A, BACKEND, DEVICE, PIN_SESSION } from '@/test/fixtures/reporter';
import { cookiesMock, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { answer, backendAnswers, resetSeenBackend, seenBackend } from '@/test/preSessionCalls';
import { asReporter, REPORTER_TOKEN } from '@/test/reporterCalls';
import { TENANTS } from '@/test/tenants';
import { GET as key } from './key/route';
import { POST as subscribe } from './subscriptions/route';
import { POST as pushTest } from './test/route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// Web push for the reporter (W34, W7C DEC-824, W8E, DEC-661). The VAPID public key comes from the back
// end (it is not a secret, and is the platform's); the subscription is saved from the All-set page,
// after sign-in, for the device the session was made on, with the consent wording; the test push goes
// to the reporter's own phone. The service worker holds none of this: the browser keeps the key and
// the subscription, the BFF holds the token.

const PUBLIC_KEY = 'BPublicKeyValueSample_0123456789-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
const SUBSCRIPTION = { endpoint: 'https://push.example.test/send/abc123', keys: { p256dh: 'p256dh-sample', auth: 'auth-sample' } };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeenBackend();
});
afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/push/key', () => {
  const call = (host: string = A.host) => key(requestWithCookies(`https://${host}/api/bff/push/key`, {}, { headers: { Host: host } }));

  it('reads the public key from the back end, addressed to the host, with no bearer, and answers it', async () => {
    answer(backendAnswers('get', '/public/push-key', 200, { publicKey: PUBLIC_KEY }));
    const response = await call();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ publicKey: PUBLIC_KEY });
    expect(seenBackend).toEqual([{ method: 'GET', path: '/public/push-key', host: A.host, authorization: null, body: undefined }]);
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it('asks the host the phone came to', async () => {
    answer(backendAnswers('get', '/public/push-key', 200, { publicKey: PUBLIC_KEY }));
    await call(TENANTS.B.host);
    expect(seenBackend[0]?.host).toBe(TENANTS.B.host);
  });

  it('answers 503 when the back end has no key (not configured) or cannot be reached, and never a key it did not send', async () => {
    for (const [status, body] of [[503, { code: 'not-configured' }], [500, {}], [404, {}]] as const) {
      answer(backendAnswers('get', '/public/push-key', status, body));
      const response = await call();
      expect(response.status, `${status}`).toBe(503);
      expect(await response.json()).toEqual({ code: 'unavailable' });
    }
  });

  it.each([{}, { publicKey: 7 }, { publicKey: '' }, { publicKey: 'has space' }, { publicKey: 'a'.repeat(300) }, { publicKey: 'a+b/c=' }])('refuses a key that is not base64url text (%j)', async (body) => {
    answer(backendAnswers('get', '/public/push-key', 200, body));
    expect((await call()).status).toBe(503);
  });
});

describe('POST /api/bff/push/subscriptions', () => {
  const call = (body: unknown, options: Parameters<typeof asReporter>[1] = {}) => asReporter(subscribe, { method: 'POST', body, ...options });
  const BODY = { subscription: SUBSCRIPTION, consentWordingVersion: 'v1' };
  const PATH = '/identity/push-subscription';

  it('saves the subscription for the device the session was made on, with the consent wording, the token and a key', async () => {
    answer(backendAnswers('post', PATH, 200, { saved: true, consentAt: '2026-10-30T10:00:00+00:00' }));
    const response = await call(BODY);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ saved: true });
    expect(seenBackend[0]).toMatchObject({ path: PATH, authorization: `Bearer ${REPORTER_TOKEN}`, body: { subscription: SUBSCRIPTION, wordingVersion: 'v1', deviceId: DEVICE } });
    expect(seenBackend[0]?.authorization).not.toContain(PIN_SESSION);
  });

  it('sends an Idempotency-Key, and uses the one the screen sent when it sent one', async () => {
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('@/test/msw/server');
    const keys: (string | null)[] = [];
    server.use(http.post(`${BACKEND}${PATH}`, ({ request }) => (keys.push(request.headers.get('idempotency-key')), HttpResponse.json({ saved: true }))));
    await call(BODY);
    await call(BODY, { headers: { 'Idempotency-Key': 'screen-key-0001' } });
    expect(keys[0]).toMatch(/^[A-Za-z0-9-]{8,64}$/);
    expect(keys[1]).toBe('screen-key-0001');
  });

  it('takes the device from the session, never from the request: a body that names a device is refused', async () => {
    expect((await call({ ...BODY, deviceId: 'E'.repeat(22) })).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it.each([
    ['no subscription', { consentWordingVersion: 'v1' }],
    ['a wording that is not v1', { subscription: SUBSCRIPTION, consentWordingVersion: 'v0' }],
    ['no wording', { subscription: SUBSCRIPTION }],
    ['a subscription with no endpoint', { subscription: { keys: SUBSCRIPTION.keys }, consentWordingVersion: 'v1' }],
    ['an endpoint that is not https', { subscription: { ...SUBSCRIPTION, endpoint: 'http://push.example.test/x' }, consentWordingVersion: 'v1' }],
    ['an endpoint that is not an address', { subscription: { ...SUBSCRIPTION, endpoint: 'not a url' }, consentWordingVersion: 'v1' }],
    ['an endpoint of more than 2048 characters', { subscription: { ...SUBSCRIPTION, endpoint: `https://push.example.test/${'a'.repeat(2048)}` }, consentWordingVersion: 'v1' }],
    ['keys that are missing', { subscription: { endpoint: SUBSCRIPTION.endpoint }, consentWordingVersion: 'v1' }],
    ['keys that are not text', { subscription: { endpoint: SUBSCRIPTION.endpoint, keys: { p256dh: 1, auth: 2 } }, consentWordingVersion: 'v1' }],
    ['a field it does not take', { ...BODY, tenant: 'trust-b' }],
  ])('refuses %s, 400, before the back end', async (_name, body) => {
    expect((await call(body)).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('passes on only the endpoint, the keys and the expiry of the subscription', async () => {
    answer(backendAnswers('post', PATH, 200, { saved: true }));
    await call({ subscription: { ...SUBSCRIPTION, expirationTime: null, extra: 'x' }, consentWordingVersion: 'v1' });
    expect(seenBackend[0]?.body).toMatchObject({ subscription: SUBSCRIPTION });
    expect(JSON.stringify(seenBackend[0]?.body)).not.toContain('extra');
  });

  it('answers a refusal as a refusal: 401 ends the session, 400 is a 400, anything else is not a save', async () => {
    answer(backendAnswers('post', PATH, 401, {}));
    expect((await call(BODY)).status).toBe(401);
    answer(backendAnswers('post', PATH, 400, { resourceType: 'OperationOutcome', issue: [{ code: 'invalid' }] }));
    expect((await call(BODY)).status).toBe(400);
    answer(backendAnswers('post', PATH, 500, {}));
    const failed = await call(BODY);
    expect(failed.status).toBe(500);
    expect(await failed.text()).not.toContain('"saved":true');
  });

  it('does not say saved for a 200 that does not say so', async () => {
    answer(backendAnswers('post', PATH, 200, {}));
    expect((await call(BODY)).status).toBe(502);
  });

  it('refuses a write with no CSRF token, and any role but reporter, before the back end', async () => {
    expect((await call(BODY, { csrf: false })).status).toBe(403);
    expect((await call(BODY, { role: 'lead' })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });

  it('never logs or answers the subscription', async () => {
    answer(backendAnswers('post', PATH, 200, { saved: true }));
    const spy = vi.spyOn(console, 'log');
    const text = await (await call(BODY)).text();
    expect(text).not.toContain(SUBSCRIPTION.endpoint);
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

// An executive holds no post and no phone session: their session is the directory's, with no device. They
// may save a subscription for their phone and ask for a test notification, nothing else of the reporter's
// app (W9H, DEC-1040). The device the back end keeps the subscription under is derived from the
// subscription's endpoint (a stable id for this browser, 43 base64url characters, never sent by the page),
// and the consent wording is the executive's own (`exec-v1`).
describe('an executive on the push routes', () => {
  const asExec = (route: Parameters<typeof asReporter>[0], options: Parameters<typeof asReporter>[1] = {}) =>
    asReporter(route, { method: 'POST', role: 'exec', session: { device: undefined, pinSession: undefined, tokenExpiresAt: undefined, services: [] }, ...options });
  const BODY = { subscription: SUBSCRIPTION, consentWordingVersion: 'exec-v1' };
  const PATH = '/identity/push-subscription';
  const derived = createHash('sha256').update(SUBSCRIPTION.endpoint).digest('base64url');

  it('saves the subscription under a device derived from its endpoint, with the executive wording and their token', async () => {
    answer(backendAnswers('post', PATH, 200, { saved: true, consentAt: '2026-10-30T10:00:00+00:00' }));
    const response = await asExec(subscribe, { body: BODY });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ saved: true });
    expect(derived).toHaveLength(43);
    expect(seenBackend[0]).toMatchObject({ path: PATH, authorization: `Bearer ${REPORTER_TOKEN}`, body: { subscription: SUBSCRIPTION, wordingVersion: 'exec-v1', deviceId: derived } });
  });

  it('derives the same device for the same endpoint and another for another browser', async () => {
    answer(backendAnswers('post', PATH, 200, { saved: true }));
    await asExec(subscribe, { body: BODY });
    await asExec(subscribe, { body: BODY });
    await asExec(subscribe, { body: { ...BODY, subscription: { ...SUBSCRIPTION, endpoint: 'https://push.example.test/send/other' } } });
    const ids = seenBackend.map((call) => (call.body as { deviceId: string }).deviceId);
    expect(ids[0]).toBe(ids[1]);
    expect(ids[2]).not.toBe(ids[0]);
  });

  it('still refuses a body that names a device, and each role its own wording', async () => {
    expect((await asExec(subscribe, { body: { ...BODY, deviceId: 'E'.repeat(22) } })).status).toBe(400);
    expect((await asExec(subscribe, { body: { ...BODY, consentWordingVersion: 'v1' } })).status).toBe(400);
    expect((await asReporter(subscribe, { method: 'POST', body: { ...BODY } })).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('asks for a test notification with the executive token', async () => {
    answer(backendAnswers('post', '/reporter/push-test', 200, { queued: true }));
    const response = await asExec(pushTest, { body: {} });
    expect(response.status).toBe(200);
    expect(seenBackend[0]).toMatchObject({ path: '/reporter/push-test', authorization: `Bearer ${REPORTER_TOKEN}` });
  });

  it('refuses every other role on both routes, before the back end (a lead, an advisor)', async () => {
    for (const role of ['lead', 'advisor'] as const) {
      expect((await asReporter(subscribe, { method: 'POST', body: BODY, role })).status).toBe(403);
      expect((await asReporter(pushTest, { method: 'POST', body: {}, role })).status).toBe(403);
    }
    expect(seenBackend).toEqual([]);
  });
});

describe('POST /api/bff/push/test', () => {
  const call = (options: Parameters<typeof asReporter>[1] = {}) => asReporter(pushTest, { method: 'POST', body: {}, ...options });
  const PATH = '/reporter/push-test';

  it('asks the back end to send a test to the reporter’s own phone, with the token', async () => {
    answer(backendAnswers('post', PATH, 200, { queued: true }));
    const response = await call();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ queued: true });
    expect(seenBackend[0]).toMatchObject({ path: PATH, authorization: `Bearer ${REPORTER_TOKEN}`, body: {} });
  });

  it('answers “no subscription saved” (409) and “too many” (429, with the wait) as themselves', async () => {
    answer(backendAnswers('post', PATH, 409, { code: 'no-subscription' }));
    const none = await call();
    expect(none.status).toBe(409);
    expect(await none.json()).toEqual({ code: 'no-subscription' });
    answer(backendAnswers('post', PATH, 429, { resourceType: 'OperationOutcome', issue: [{ code: 'throttled' }] }, { 'Retry-After': '600' }));
    const limited = await call();
    expect(limited.status).toBe(429);
    expect(limited.headers.get('Retry-After')).toBe('600');
  });

  it('does not say queued for a 200 that does not say so, and refuses a body that is not empty and a write with no CSRF token', async () => {
    answer(backendAnswers('post', PATH, 200, {}));
    expect((await call()).status).toBe(502);
    seenBackend.length = 0;
    expect((await asReporter(pushTest, { method: 'POST', body: { tenant: 'trust-b' } })).status).toBe(400);
    expect((await call({ csrf: false })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });
});
