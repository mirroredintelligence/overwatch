// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, unsealSession, type Session } from '@/lib/auth/session';
import { A, BACKEND, DEVICE, exchangeBody, exchangeHandler, iso, PERSON, PIN_SESSION, reporterToken, type SeenExchange } from '@/test/fixtures/reporter';
import { cookieWrites, cookiesMock, lastWrite, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { RENEW_BEFORE_MS, renewIfDue } from './renew';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The refresh of the reporter's token (W8E, DEC-792). The token lasts 30 minutes and cannot be
// recalled; the PIN session can. So the BFF asks again from the live PIN session when the token has
// five minutes left (or has run out), and the session ends the moment the back end will not give a
// new one. The session's own end (eight hours) is never moved by a renewal, and the tenant, host,
// person and phone it was made for never change.

const NOW = new Date('2026-10-30T09:00:00Z');
const SESSION_END = new Date(NOW.getTime() + 6 * 3_600_000);
const seen: SeenExchange[] = [];
let reply: Parameters<typeof exchangeHandler>[1];

function reporterSession(tokenLeftMs: number, over: Partial<Session> = {}): Session {
  const expires = new Date(NOW.getTime() + tokenLeftMs);
  return {
    role: 'reporter',
    tenantId: A.id,
    host: A.host,
    services: ['s1'],
    sub: PERSON,
    device: DEVICE,
    backendToken: reporterToken({ exp: Math.floor(expires.getTime() / 1000) }, new Date(expires.getTime() - 30 * 60_000)),
    pinSession: PIN_SESSION,
    tokenExpiresAt: iso(expires),
    expiresAt: iso(SESSION_END),
    ...over,
  };
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
  seen.length = 0;
  reply = () => ({ body: exchangeBody({}, { services: ['s1', 's2'] }, new Date()) });
  server.use(exchangeHandler(seen, () => reply()));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe('renewIfDue: when it asks', () => {
  it('does not ask for a session that has no PIN session (a staff session, or a registrant’s token)', async () => {
    const session = reporterSession(0, { pinSession: undefined, tokenExpiresAt: undefined });
    expect(await renewIfDue(session, NOW)).toEqual({ kind: 'current', session });
    expect(seen).toHaveLength(0);
  });

  it('does not ask while the token has more than five minutes left', async () => {
    const session = reporterSession(RENEW_BEFORE_MS + 1000);
    expect(await renewIfDue(session, NOW)).toEqual({ kind: 'current', session });
    expect(seen).toHaveLength(0);
    expect(cookieWrites).toEqual([]);
  });

  it('asks at five minutes left, and when the token has run out', async () => {
    for (const left of [RENEW_BEFORE_MS, 1000, 0, -45 * 60_000]) {
      seen.length = 0;
      const renewal = await renewIfDue(reporterSession(left), NOW);
      expect(renewal.kind, `${left}`).toBe('renewed');
      expect(seen, `${left}`).toHaveLength(1);
    }
  });

  it('asks once for several calls that find the token due at the same moment', async () => {
    const session = reporterSession(1000);
    const all = await Promise.all([renewIfDue(session, NOW), renewIfDue(session, NOW), renewIfDue(session, NOW)]);
    expect(all.map((r) => r.kind)).toEqual(['renewed', 'renewed', 'renewed']);
    expect(seen).toHaveLength(1);
  });

  it('asks again for a later call once the first has finished', async () => {
    await renewIfDue(reporterSession(1000), NOW);
    await renewIfDue(reporterSession(1000), NOW);
    expect(seen).toHaveLength(2);
  });
});

describe('renewIfDue: what a renewal changes and what it never does', () => {
  it('gives the new token, its expiry and the services the token names, and seals them in the session cookie', async () => {
    const before = reporterSession(1000);
    const renewal = await renewIfDue(before, NOW);
    if (renewal.kind !== 'renewed') throw new Error('expected a renewal');
    expect(renewal.session.backendToken).not.toBe(before.backendToken);
    expect(renewal.session.tokenExpiresAt).toBe(iso(new Date(NOW.getTime() + 30 * 60_000)));
    expect(renewal.session.services).toEqual(['s1', 's2']);
    const sealed = lastWrite(SESSION_COOKIE);
    expect(sealed?.options).toMatchObject({ httpOnly: true, sameSite: 'strict' });
    expect(await unsealSession(sealed?.value ?? '', NOW)).toEqual(renewal.session);
  });

  it('keeps the person, tenant, host, phone, PIN session and the session’s own end exactly', async () => {
    const before = reporterSession(1000);
    const renewal = await renewIfDue(before, NOW);
    if (renewal.kind !== 'renewed') throw new Error('expected a renewal');
    expect(renewal.session).toMatchObject({
      role: 'reporter',
      sub: before.sub,
      tenantId: before.tenantId,
      host: before.host,
      device: before.device,
      pinSession: before.pinSession,
      expiresAt: before.expiresAt,
    });
  });

  it('does not lengthen the cookie: it still ends when the session ends', async () => {
    await renewIfDue(reporterSession(1000), NOW);
    expect(lastWrite(SESSION_COOKIE)?.options.maxAge).toBe(6 * 3600);
  });

  it('asks the session’s own host, with the PIN session id only, and sends no bearer', async () => {
    await renewIfDue(reporterSession(1000), NOW);
    expect(seen).toEqual([{ host: A.host, authorization: null, body: { sessionId: PIN_SESSION } }]);
  });

  it('writes no cookie when it does not renew', async () => {
    reply = () => ({ status: 404, body: {} });
    await renewIfDue(reporterSession(1000), NOW);
    expect(cookieWrites.filter((w) => w.name === SESSION_COOKIE)).toEqual([]);
  });
});

describe('renewIfDue: a renewal that fails', () => {
  it.each([400, 401, 403, 404, 410])('ends the session when the back end refuses it with %i', async (status) => {
    reply = () => ({ status, body: {} });
    expect(await renewIfDue(reporterSession(1000), NOW)).toEqual({ kind: 'ended' });
  });

  it.each([
    ['another tenant', { tenant: 'trust-b' }],
    ['another person', { sub: 'prac-someone-else-0123456789abcdef0' }],
    ['another phone', { device: 'E'.repeat(22) }],
    ['a role that is not reporter', { role: 'lead' }],
    ['an expired token', { exp: Math.floor(NOW.getTime() / 1000) - 5 }],
  ])('ends the session at once when the answer is for %s, even with the old token still good', async (_name, claims) => {
    reply = () => ({ body: exchangeBody({}, claims as never, new Date()) });
    expect(await renewIfDue(reporterSession(RENEW_BEFORE_MS - 1000), NOW)).toEqual({ kind: 'ended' });
  });

  it('keeps the old token while it is still good when the back end cannot be asked, and asks again next time', async () => {
    reply = () => 'network-error';
    const session = reporterSession(2 * 60_000);
    expect(await renewIfDue(session, NOW)).toEqual({ kind: 'current', session });
    reply = () => ({ body: exchangeBody({}, {}, new Date()) });
    expect((await renewIfDue(session, NOW)).kind).toBe('renewed');
  });

  it.each([429, 500, 503])('treats a %i as unavailable: the old token stays while it lasts', async (status) => {
    reply = () => ({ status, body: {} });
    const session = reporterSession(60_000);
    expect(await renewIfDue(session, NOW)).toEqual({ kind: 'current', session });
  });

  it('ends the session when the token has run out and the back end cannot be asked', async () => {
    reply = () => 'network-error';
    expect(await renewIfDue(reporterSession(0), NOW)).toEqual({ kind: 'ended' });
    expect(await renewIfDue(reporterSession(-1), NOW)).toEqual({ kind: 'ended' });
  });

  it('writes no session cookie when it ends the session (the caller clears it)', async () => {
    reply = () => ({ status: 404, body: {} });
    await renewIfDue(reporterSession(0), NOW);
    expect(cookieWrites.filter((w) => w.name === SESSION_COOKIE)).toEqual([]);
  });
});
