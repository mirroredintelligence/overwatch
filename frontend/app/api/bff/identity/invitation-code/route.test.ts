// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { A, BACKEND } from '@/test/fixtures/reporter';
import { cookiesMock, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { answer, backendAnswers, phoneCall, resetSeenBackend, seenBackend } from '@/test/preSessionCalls';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The set-up text code of an invitation (W33, W8E, DEC-811). The browser holds the link's token and the
// phone's device cookie, never a number: the back end finds the number through the invitation. It
// answers 202 whatever the token is, and so does this route.

const TOKEN = 'SampleInvitationToken1';
const PATH = `/identity/invitations/${TOKEN}/code`;
const ACCEPTED = { accepted: true, resendAfterSeconds: 60 };
const call = (body: unknown, options = {}) => phoneCall(POST, '/api/bff/identity/invitation-code', body, options);

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeenBackend();
});
afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/identity/invitation-code', () => {
  it('asks the back end for the code of this invitation, addressed to the host, with an empty body and no bearer', async () => {
    answer(backendAnswers('post', PATH, 202, ACCEPTED));
    const response = await call({ invite: TOKEN });
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual(ACCEPTED);
    expect(seenBackend).toEqual([{ method: 'POST', path: PATH, host: A.host, authorization: null, body: {} }]);
  });

  it('answers the back end’s own wait, and 60 when it names none', async () => {
    answer(backendAnswers('post', PATH, 202, { accepted: true, resendAfterSeconds: 45 }));
    expect(await (await call({ invite: TOKEN })).json()).toEqual({ accepted: true, resendAfterSeconds: 45 });
    answer(backendAnswers('post', PATH, 202, {}));
    expect(await (await call({ invite: TOKEN })).json()).toEqual(ACCEPTED);
  });

  it.each([
    ['no invitation', {}],
    ['an invitation that cannot be one', { invite: 'bad token!' }],
    ['a number', { invite: TOKEN, phone: '07700900123' }],
    ['a tenant', { invite: TOKEN, tenant: 'trust-b' }],
    ['a device', { invite: TOKEN, deviceId: 'D'.repeat(22) }],
    ['an invitation that is not text', { invite: 7 }],
    ['text that is not JSON', 'invite=1'],
  ])('refuses %s with 400, without calling the back end', async (_name, body) => {
    const response = await call(body);
    expect(response.status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('refuses a write with no CSRF token of this phone, 403, before the back end', async () => {
    const response = await call({ invite: TOKEN }, { csrf: false });
    expect(response.status).toBe(403);
    expect(seenBackend).toEqual([]);
  });

  it('says 429 with a retry time when the address is limited, 503 when the back end cannot say or answers anything else', async () => {
    answer(backendAnswers('post', PATH, 429, {}, { 'Retry-After': '600' }));
    const limited = await call({ invite: TOKEN });
    expect(limited.status).toBe(429);
    expect(limited.headers.get('Retry-After')).toBe('600');
    for (const status of [404, 500, 503, 200]) {
      answer(backendAnswers('post', PATH, status, {}));
      expect((await call({ invite: TOKEN })).status, `${status}`).toBe(503);
    }
  });

  it('is never stored and does not echo the token', async () => {
    answer(backendAnswers('post', PATH, 202, ACCEPTED));
    const response = await call({ invite: TOKEN });
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(await response.text()).not.toContain(TOKEN);
  });
});
