// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { A, BACKEND } from '@/test/fixtures/reporter';
import { cookiesMock, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { answer, backendAnswers, resetSeenBackend, seenBackend } from '@/test/preSessionCalls';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The invitation a reporter's link names (W33, W8E, DEC-810). The back end reads it by its link token, in
// the host's tenant, and answers the service, the post, the masked number and the expiry; anything that
// cannot be used is one 410 `{state: "expired"}`. The BFF passes on only those fields, and says "valid"
// only when the back end did.

const TOKEN = 'SampleInvitationToken1';
const VALID = { state: 'valid', service: 'UCR West', role: 'reporter', maskedPhone: '07xxx xxx456', expiresAt: '2026-11-01T10:00:00Z' };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeenBackend();
});
afterEach(() => vi.unstubAllEnvs());

const call = (token: string = TOKEN, host: string = A.host) =>
  GET(requestWithCookies(`https://${host}/api/bff/invitations/${token}`, {}, { headers: { Host: host } }), { params: Promise.resolve({ token }) });

describe('GET /api/bff/invitations/[token]', () => {
  it('reads the invitation from the back end by its token, addressed to the host, with no bearer', async () => {
    answer(backendAnswers('get', `/invitations/${TOKEN}`, 200, VALID));
    const response = await call();
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(VALID);
    expect(seenBackend).toEqual([{ method: 'GET', path: `/invitations/${TOKEN}`, host: A.host, authorization: null, body: undefined }]);
  });

  it('passes on the fields the page reads and no others', async () => {
    answer(backendAnswers('get', `/invitations/${TOKEN}`, 200, { ...VALID, person: 'prac-1', tenant: A.id, phone: '07700900123' }));
    const body = (await (await call()).json()) as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(['expiresAt', 'maskedPhone', 'role', 'service', 'state']);
  });

  it('asks the host the phone came to: tenant B’s host reaches the back end as tenant B’s host', async () => {
    answer(backendAnswers('get', `/invitations/${TOKEN}`, 410, { state: 'expired' }));
    await call(TOKEN, TENANTS.B.host);
    expect(seenBackend[0]?.host).toBe(TENANTS.B.host);
  });

  it('answers the one 410 expired for whatever the back end will not use, and says nothing more', async () => {
    answer(backendAnswers('get', `/invitations/${TOKEN}`, 410, { state: 'expired', reason: 'used', tenant: A.id }));
    const response = await call();
    expect(response.status).toBe(410);
    expect(await response.json()).toEqual({ state: 'expired' });
  });

  it('refuses a token that cannot be an invitation with the same 410, without calling the back end', async () => {
    for (const bad of ['bad token!', 'a'.repeat(65), 'a/b', '%2e%2e']) {
      const response = await call(bad);
      expect(response.status, bad).toBe(410);
      expect(await response.json()).toEqual({ state: 'expired' });
    }
    expect(seenBackend).toEqual([]);
  });

  it('says 429 when the back end limits the address, and 503 when it cannot say', async () => {
    answer(backendAnswers('get', `/invitations/${TOKEN}`, 429, {}));
    expect((await call()).status).toBe(429);
    for (const status of [500, 502, 503]) {
      answer(backendAnswers('get', `/invitations/${TOKEN}`, status, {}));
      const response = await call();
      expect(response.status).toBe(503);
      expect(await response.json()).toEqual({ code: 'unavailable' });
    }
  });

  it.each([
    ['a 200 that says it is not valid', { ...VALID, state: 'expired' }],
    ['a 200 with no service', { ...VALID, service: undefined }],
    ['a 200 with a masked number that is not text', { ...VALID, maskedPhone: 7 }],
    ['a 200 with no expiry', { ...VALID, expiresAt: undefined }],
    ['a 200 that is not an object', ['valid']],
  ])('never says valid for %s', async (_name, body) => {
    answer(backendAnswers('get', `/invitations/${TOKEN}`, 200, body));
    const response = await call();
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ code: 'unavailable' });
  });

  it('is never stored, and does not echo the token', async () => {
    answer(backendAnswers('get', `/invitations/${TOKEN}`, 200, VALID));
    const response = await call();
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(await response.text()).not.toContain(TOKEN);
  });

  it('does not answer not-built any more', async () => {
    answer(backendAnswers('get', `/invitations/${TOKEN}`, 200, VALID));
    expect(await (await call()).text()).not.toContain('not-built');
  });
});
