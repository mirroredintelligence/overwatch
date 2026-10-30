// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND, PIN_SESSION } from '@/test/fixtures/reporter';
import { cookiesMock, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { answer, backendAnswers, resetSeenBackend, seenBackend } from '@/test/preSessionCalls';
import { asReporter, REPORTER_TOKEN } from '@/test/reporterCalls';
import { GET as bookingRead } from './bookings/[ref]/route';
import { GET as history } from './services/[serviceId]/history/route';
import { GET as prompt } from './services/[serviceId]/prompt/route';
import { GET as services } from './services/route';
import { GET as settings } from './settings/route';
import { GET as setupSummary } from './setup-summary/route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The reporter's reads, wired to the back end (W7C, DEC-814 to DEC-826; W8E). Each one carries the
// reporter's token and nothing that names a tenant, passes on only the fields a screen reads (with the
// shape checked, so nothing unexpected is shown), and answers what the back end answers: a service the
// reporter does not hold is the one 404, a session the back end no longer knows is the end of the
// session. The BFF does not decide which services are the reporter's: the back end reads them from the
// graph at the time of the request (DEC-814), so a cover that began after sign-in works at once.

const ROW = { id: 's1', name: 'UCR West', state: 'due', recordedValue: 3, unitLabel: 'referrals in the next 2 hrs', at: '2026-10-30T08:15:00Z', nextDue: '2026-10-30T12:00:00Z', pendingAcceptance: false, letter: 'A', replyBy: '2026-10-30T10:30:00Z' };
const PROMPT = { service: 'UCR West', unitLabel: 'referrals in the next 2 hrs', recordedValue: 3, asOf: '2026-10-30T08:15:00Z', low: 0, high: 8, replyBy: '2026-10-30T10:30:00Z', nextDue: '2026-10-30T12:00:00Z' };
const HISTORY = { items: [{ at: '2026-10-30T10:12:00Z', value: 3, kind: 'number' }, { at: '2026-10-30T08:15:00Z', value: 2, kind: 'confirm' }] };
const SETTINGS = { channel: 'app', maskedPhone: '07xxx xxx456', maskedCover: null, reverifyInDays: 21, otherDevices: 1 };
const SUMMARY = { service: 'UCR West', contactBy: 'app', maskedPhone: '07xxx xxx456', nextUpdateDue: '2026-10-30T12:00:00Z', textCodeInDays: 30 };
const BOOKING = { reference: '4821', taskId: 'task-internal-1', service: 'UCR West', ageBand: '80+', need: 'Fall and frailty', urgency: 'Wanted within 2 hrs', replyBy: '2026-10-30T14:26:00Z', status: 'requested', bookingStatus: 'requested', multiService: false, spoaPhone: '01632 960001' };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeenBackend();
});
afterEach(() => vi.unstubAllEnvs());

type Case = {
  name: string;
  route: Parameters<typeof asReporter>[0];
  url: string;
  backend: string;
  params?: Record<string, string>;
  sample: unknown;
  expected: unknown;
  /** A field the back end sends that the screen must not get. */
  extra?: Record<string, unknown>;
  broken: unknown[];
};

const CASES: Case[] = [
  { name: 'services', route: services, url: '/api/bff/reporter/services', backend: '/reporter/services', sample: { services: [ROW] }, expected: { services: [ROW] }, extra: { internal: 'x' }, broken: [{}, { services: 'none' }, { services: [{ ...ROW, state: 'sleeping' }] }, { services: [{ ...ROW, id: 7 }] }, { services: [{ ...ROW, recordedValue: 'three' }] }, { services: [{ ...ROW, at: 'noon' }] }, { services: [{ ...ROW, pendingAcceptance: 'no' }] }] },
  { name: 'prompt', route: prompt, url: '/api/bff/reporter/services/s1/prompt', backend: '/reporter/services/s1/prompt', params: { serviceId: 's1' }, sample: PROMPT, expected: PROMPT, extra: { internal: 'x' }, broken: [{}, { ...PROMPT, low: 'a' }, { ...PROMPT, service: undefined }, { ...PROMPT, asOf: 'noon' }, { ...PROMPT, high: 99999 }] },
  { name: 'history', route: history, url: '/api/bff/reporter/services/s1/history?day=today', backend: '/reporter/services/s1/history?day=today', params: { serviceId: 's1' }, sample: HISTORY, expected: HISTORY, broken: [{}, { items: 'x' }, { items: [{ at: 'noon', value: 3, kind: 'number' }] }, { items: [{ at: '2026-10-30T10:12:00Z', value: 'x', kind: 'number' }] }] },
  { name: 'settings', route: settings, url: '/api/bff/reporter/settings', backend: '/reporter/settings', sample: SETTINGS, expected: SETTINGS, extra: { phone: '07700900123' }, broken: [{}, { ...SETTINGS, channel: 'fax' }, { ...SETTINGS, reverifyInDays: 'soon' }, { ...SETTINGS, maskedPhone: 7 }, { ...SETTINGS, maskedCover: 5 }] },
  { name: 'setup-summary', route: setupSummary, url: '/api/bff/reporter/setup-summary', backend: '/reporter/setup-summary', sample: SUMMARY, expected: SUMMARY, extra: { phone: '07700900123' }, broken: [{}, { ...SUMMARY, service: 7 }, { ...SUMMARY, textCodeInDays: 'x' }, { ...SUMMARY, nextUpdateDue: 'noon' }] },
  { name: 'booking by reference', route: bookingRead, url: '/api/bff/reporter/bookings/4821', backend: '/reporter/bookings/4821', params: { ref: '4821' }, sample: BOOKING, expected: { reference: '4821', service: 'UCR West', ageBand: '80+', need: 'Fall and frailty', urgency: 'Wanted within 2 hrs', replyBy: '2026-10-30T14:26:00Z', status: 'requested', bookingStatus: 'requested', multiService: false, spoaPhone: '01632 960001' }, broken: [{}, { ...BOOKING, status: 'maybe' }, { ...BOOKING, replyBy: 'late' }, { ...BOOKING, multiService: 'yes' }, { ...BOOKING, reference: 4821 }] },
];

describe.each(CASES)('$name', (c) => {
  const call = (options: Parameters<typeof asReporter>[1] = {}) => asReporter(c.route, { path: c.url, params: c.params, ...options });

  it('asks the back end with the reporter’s token, never the PIN session, and nothing that names a tenant', async () => {
    answer(backendAnswers('get', c.backend.split('?')[0]!, 200, c.sample));
    expect((await call()).status).toBe(200);
    expect(seenBackend).toHaveLength(1);
    expect(seenBackend[0]?.authorization).toBe(`Bearer ${REPORTER_TOKEN}`);
    expect(seenBackend[0]?.authorization).not.toContain(PIN_SESSION);
  });

  it('passes on the fields the screen reads, with their shape checked, and no others', async () => {
    answer(backendAnswers('get', c.backend.split('?')[0]!, 200, Array.isArray(c.sample) ? c.sample : { ...(c.sample as object), ...c.extra }));
    const response = await call();
    expect(await response.json()).toEqual(c.expected);
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it.each(c.broken.map((b, i) => [i, b] as const))('refuses an answer that is not the back end’s shape (%i), as a failure and not as data', async (_i, body) => {
    answer(backendAnswers('get', c.backend.split('?')[0]!, 200, body));
    const response = await call();
    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({ code: 'exception' });
  });

  it('answers the back end’s 404 as the one 404, and a 401 as the end of the session', async () => {
    answer(backendAnswers('get', c.backend.split('?')[0]!, 404, { resourceType: 'OperationOutcome', issue: [{ code: 'not-found' }] }));
    const missing = await call();
    expect(missing.status).toBe(404);
    expect(await missing.json()).toMatchObject({ code: 'not-found' });
    answer(backendAnswers('get', c.backend.split('?')[0]!, 401, { resourceType: 'OperationOutcome', issue: [{ code: 'login' }] }));
    const ended = await call();
    expect(ended.status).toBe(401);
    expect(await ended.json()).toMatchObject({ code: 'session-ended' });
  });

  it('answers 503 when the back end cannot be reached, and does not answer not-built', async () => {
    answer(backendAnswers('get', c.backend.split('?')[0]!, 503, {}));
    const response = await call();
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain('not-built');
  });

  it('is for a reporter: another role gets 403 and the back end is not asked', async () => {
    expect((await call({ role: 'lead' })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });
});

describe('what a route takes from the caller', () => {
  it('a service the cookie does not list still goes to the back end, which decides (a cover that began after sign-in)', async () => {
    answer(backendAnswers('get', '/reporter/services/s7/prompt', 200, PROMPT));
    const response = await asReporter(prompt, { path: '/api/bff/reporter/services/s7/prompt', params: { serviceId: 's7' }, session: { services: ['s1'] } });
    expect(response.status).toBe(200);
    expect(seenBackend[0]?.path).toBe('/reporter/services/s7/prompt');
  });

  it('a service in another tenant is the back end’s 404, the same body as one that does not exist', async () => {
    answer(backendAnswers('get', '/reporter/services/other/prompt', 404, {}), backendAnswers('get', '/reporter/services/nowhere/prompt', 404, {}));
    const other = await asReporter(prompt, { path: '/x', params: { serviceId: 'other' } });
    const none = await asReporter(prompt, { path: '/x', params: { serviceId: 'nowhere' } });
    expect(other.status).toBe(404);
    expect(await other.text()).toBe(await none.text());
  });

  it.each(['a b', 'a/b', '..', '%2e%2e', 'x'.repeat(65), ''])('a service id of %j is the 404, and the back end is not asked', async (serviceId) => {
    for (const route of [prompt, history]) {
      const response = await asReporter(route, { path: '/x?day=today', params: { serviceId } });
      expect(response.status).toBe(404);
    }
    expect(seenBackend).toEqual([]);
  });

  it('a history for another day than today is refused, 400', async () => {
    for (const query of ['?day=yesterday', '?day=', '?day=today&day=all', '?from=2026-10-01']) {
      expect((await asReporter(history, { path: `/api/bff/reporter/services/s1/history${query}`, params: { serviceId: 's1' } })).status, query).toBe(400);
    }
    expect(seenBackend).toEqual([]);
  });

  it.each(['4821x', '482', '48210', 'abcd', '48 1', '../1'])('a booking reference of %j is the 404, and the back end is not asked', async (ref) => {
    expect((await asReporter(bookingRead, { path: '/x', params: { ref } })).status).toBe(404);
    expect(seenBackend).toEqual([]);
  });

  it('a booking read never shows the Task id', async () => {
    answer(backendAnswers('get', '/reporter/bookings/4821', 200, BOOKING));
    expect(await (await asReporter(bookingRead, { path: '/x', params: { ref: '4821' } })).text()).not.toContain('task-internal-1');
  });

  it('a booking with no age band, urgency or SPOA number passes on nulls', async () => {
    answer(backendAnswers('get', '/reporter/bookings/4821', 200, { ...BOOKING, ageBand: null, urgency: null, spoaPhone: null }));
    expect(await (await asReporter(bookingRead, { path: '/x', params: { ref: '4821' } })).json()).toMatchObject({ ageBand: null, urgency: null, spoaPhone: null });
  });

  it('a confirmed booking passes on when it was confirmed', async () => {
    answer(backendAnswers('get', '/reporter/bookings/4821', 200, { ...BOOKING, status: 'confirmed', bookingStatus: 'confirmed', confirmedAt: '2026-10-30T14:19:00Z' }));
    expect(await (await asReporter(bookingRead, { path: '/x', params: { ref: '4821' } })).json()).toMatchObject({ status: 'confirmed', confirmedAt: '2026-10-30T14:19:00Z' });
  });

  it('a request that names a tenant is refused 400 before the back end', async () => {
    expect((await asReporter(services, { path: '/api/bff/reporter/services?tenant=trust-b' })).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });
});
