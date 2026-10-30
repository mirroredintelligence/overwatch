// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND, PIN_SESSION } from '@/test/fixtures/reporter';
import { cookiesMock, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { answer, backendAnswers, resetSeenBackend, seenBackend } from '@/test/preSessionCalls';
import { asReporter, KEY, REPORTER_TOKEN } from '@/test/reporterCalls';
import { POST as respond } from './bookings/[ref]/respond/route';
import { POST as channel } from './channel/route';
import { POST as coverAll } from './cover/route';
import { POST as batch } from './reports/batch/route';
import { POST as accept } from './services/[serviceId]/accept/route';
import { POST as coverOne } from './services/[serviceId]/cover/route';
import { POST as report } from './services/[serviceId]/report/route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The reporter's writes, wired to the back end (W7C, DEC-816 to DEC-823; W8E). Each checks the shape of
// what it is sent before the back end is asked, carries the reporter's token and (for a report, a batch
// and a booking answer) the screen's Idempotency-Key, and passes on what the back end decided: a figure
// out of range, a confirm that must become a number, a booking already answered. Nothing a back end
// refuses is turned into success, and a phone number is never in an answer.

const RECORDED = { result: 'recorded', serviceName: 'UCR West', value: 4, recordedAt: '2026-10-30T10:12:00Z', nextDue: '2026-10-30T12:00:00Z' };
const OUT_OF_RANGE = { result: 'outOfRange', serviceName: 'UCR West', value: 40, low: 0, high: 8 };
const REPORT_PATH = '/reporter/services/s1/report';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeenBackend();
});
afterEach(() => vi.unstubAllEnvs());

const post = (route: Parameters<typeof asReporter>[0], body: unknown, options: Parameters<typeof asReporter>[1] = {}) =>
  asReporter(route, { method: 'POST', headers: { 'Idempotency-Key': KEY }, body, ...options });

describe('POST /api/bff/reporter/services/[serviceId]/report', () => {
  const call = (body: unknown, options: Parameters<typeof asReporter>[1] = {}) => post(report, body, { params: { serviceId: 's1' }, ...options });

  it('sends a confirm, a number or closed with the token and the key, and answers the recorded figure', async () => {
    answer(backendAnswers('post', REPORT_PATH, 200, RECORDED));
    for (const body of [{ kind: 'confirm' }, { kind: 'number', value: 4 }, { kind: 'closed' }, { kind: 'number', value: 40, confirmOutOfRange: true }]) {
      resetSeenBackend();
      const response = await call(body);
      expect(response.status, JSON.stringify(body)).toBe(200);
      expect(await response.json()).toEqual(RECORDED);
      expect(seenBackend).toHaveLength(1);
      expect(seenBackend[0]).toMatchObject({ method: 'POST', path: REPORT_PATH, authorization: `Bearer ${REPORTER_TOKEN}`, body });
    }
  });

  it('passes the Idempotency-Key to the back end', async () => {
    let key: string | null = null;
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('@/test/msw/server');
    server.use(http.post(`${BACKEND}${REPORT_PATH}`, ({ request }) => ((key = request.headers.get('idempotency-key')), HttpResponse.json(RECORDED))));
    await call({ kind: 'confirm' });
    expect(key).toBe(KEY);
  });

  it('answers a figure out of range with the usual range, as the back end does (200)', async () => {
    answer(backendAnswers('post', REPORT_PATH, 200, OUT_OF_RANGE));
    const response = await call({ kind: 'number', value: 40 });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(OUT_OF_RANGE);
  });

  it('answers a confirm that must be a number (409 sendNumber, with the reason) and the confirm limit (409), without turning either into success', async () => {
    answer(backendAnswers('post', REPORT_PATH, 409, { result: 'sendNumber', serviceName: 'UCR West', reason: 'stale' }));
    const stale = await call({ kind: 'confirm' });
    expect(stale.status).toBe(409);
    expect(await stale.json()).toEqual({ result: 'sendNumber', serviceName: 'UCR West', reason: 'stale' });
    answer(backendAnswers('post', REPORT_PATH, 409, { result: 'confirmLimit', serviceName: 'UCR West' }));
    const limit = await call({ kind: 'confirm' });
    expect(limit.status).toBe(409);
    expect(await limit.json()).toEqual({ result: 'confirmLimit', serviceName: 'UCR West' });
  });

  it.each([
    ['an unknown kind', { kind: 'delete' }],
    ['no kind', {}],
    ['a figure that is not a whole number', { kind: 'number', value: 2.5 }],
    ['a figure below zero', { kind: 'number', value: -1 }],
    ['a figure above 999', { kind: 'number', value: 1000 }],
    ['a figure that is text', { kind: 'number', value: '4' }],
    ['a number with no figure', { kind: 'number' }],
    ['a confirm that carries a figure', { kind: 'confirm', value: 4 }],
    ['confirmOutOfRange that is not a boolean', { kind: 'number', value: 4, confirmOutOfRange: 'yes' }],
    ['a field it does not take', { kind: 'confirm', tenant: 'trust-b' }],
    ['text that is not JSON', 'kind=confirm'],
  ])('refuses %s, 400, before the back end', async (_name, body) => {
    expect((await call(body)).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it.each([undefined, 'short', 'has space!!', 'x'.repeat(65)])('refuses an Idempotency-Key of %j, 400, before the back end', async (key) => {
    const headers = key === undefined ? {} : { 'Idempotency-Key': key };
    const response = await asReporter(report, { method: 'POST', body: { kind: 'confirm' }, params: { serviceId: 's1' }, headers: { 'Idempotency-Key': '', ...headers } });
    expect(response.status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('answers the back end’s 404 as the one 404 and does not name the service', async () => {
    answer(backendAnswers('post', REPORT_PATH, 404, {}));
    const response = await call({ kind: 'confirm' });
    expect(response.status).toBe(404);
    expect(await response.text()).not.toContain('s1');
  });

  it('refuses a service id that cannot be one, 404, before the back end', async () => {
    expect((await post(report, { kind: 'confirm' }, { params: { serviceId: '../x' } })).status).toBe(404);
    expect(seenBackend).toEqual([]);
  });

  it('refuses a write with no CSRF token, before the back end, and an answer that is not the back end’s shape as a failure', async () => {
    expect((await call({ kind: 'confirm' }, { csrf: false })).status).toBe(403);
    expect(seenBackend).toEqual([]);
    answer(backendAnswers('post', REPORT_PATH, 200, { result: 'recorded' }));
    expect((await call({ kind: 'confirm' })).status).toBe(502);
    answer(backendAnswers('post', REPORT_PATH, 200, { ...RECORDED, result: 'done' }));
    expect((await call({ kind: 'confirm' })).status).toBe(502);
  });

  it('does not answer not-built any more, and never shows the PIN session', async () => {
    answer(backendAnswers('post', REPORT_PATH, 200, RECORDED));
    const text = await (await call({ kind: 'confirm' })).text();
    expect(text).not.toContain('not-built');
    expect(text).not.toContain(PIN_SESSION);
  });
});

describe('POST /api/bff/reporter/reports/batch', () => {
  const call = (body: unknown, options: Parameters<typeof asReporter>[1] = {}) => post(batch, body, options);
  const RESULTS = { results: [{ serviceId: 's1', result: 'recorded', at: '2026-10-30T10:12:00Z' }, { serviceId: 's2', result: 'sendNumber', reason: 'stale' }] };

  it('sends one to ten confirms with the token and the key, and answers each result', async () => {
    answer(backendAnswers('post', '/reporter/reports/batch', 200, RESULTS));
    const items = [{ serviceId: 's1', kind: 'confirm' }, { serviceId: 's2', kind: 'confirm' }];
    const response = await call({ items });
    expect(await response.json()).toEqual(RESULTS);
    expect(seenBackend).toHaveLength(1);
    expect(seenBackend[0]).toMatchObject({ method: 'POST', path: '/reporter/reports/batch', authorization: `Bearer ${REPORTER_TOKEN}`, body: { items } });
  });

  it('does not check the services against the cookie: the back end holds the reporter’s services (a cover that began later)', async () => {
    answer(backendAnswers('post', '/reporter/reports/batch', 200, { results: [{ serviceId: 's9', result: 'recorded', at: '2026-10-30T10:12:00Z' }] }));
    expect((await call({ items: [{ serviceId: 's9', kind: 'confirm' }] }, { session: { services: ['s1'] } })).status).toBe(200);
  });

  it('answers 404 when the back end finds one service that is not the reporter’s, and nothing was written', async () => {
    answer(backendAnswers('post', '/reporter/reports/batch', 404, {}));
    expect((await call({ items: [{ serviceId: 's1', kind: 'confirm' }, { serviceId: 'x', kind: 'confirm' }] })).status).toBe(404);
  });

  it.each([
    ['no items', { items: [] }],
    ['more than ten', { items: Array.from({ length: 11 }, (_, i) => ({ serviceId: `s${i}`, kind: 'confirm' })) }],
    ['a number in a batch', { items: [{ serviceId: 's1', kind: 'number' }] }],
    ['an item with no service', { items: [{ kind: 'confirm' }] }],
    ['a service id that cannot be one', { items: [{ serviceId: '../x', kind: 'confirm' }] }],
    ['items that are not a list', { items: 'all' }],
    ['a field it does not take', { items: [{ serviceId: 's1', kind: 'confirm' }], tenant: 'trust-b' }],
  ])('refuses %s, 400, before the back end', async (_name, body) => {
    expect((await call(body)).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('refuses a missing Idempotency-Key, and a write with no CSRF token', async () => {
    expect((await call({ items: [{ serviceId: 's1', kind: 'confirm' }] }, { headers: { 'Idempotency-Key': '' } })).status).toBe(400);
    expect((await call({ items: [{ serviceId: 's1', kind: 'confirm' }] }, { csrf: false })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });

  it('refuses an answer that is not the back end’s shape', async () => {
    answer(backendAnswers('post', '/reporter/reports/batch', 200, { results: [{ serviceId: 's1', result: 'maybe' }] }));
    expect((await call({ items: [{ serviceId: 's1', kind: 'confirm' }] })).status).toBe(502);
  });
});

describe.each([
  ['POST /api/bff/reporter/cover', coverAll, {}, '/reporter/cover'],
  ['POST /api/bff/reporter/services/[serviceId]/cover', coverOne, { serviceId: 's1' }, '/reporter/services/s1/cover'],
] as const)('%s', (_name, route, params, backendPath) => {
  const call = (body: unknown, options: Parameters<typeof asReporter>[1] = {}) => asReporter(route, { method: 'POST', body, params: { ...params }, ...options });
  const OK = { coveredUntil: '2026-10-30T23:59:00Z', services: 1 };

  it.each([
    [{ phone: '07700 900123', until: 'tonight' }],
    [{ phone: '07700900123', until: 'this-week' }],
    [{ phone: '07700900123', until: 'date', date: '2026-11-05' }],
  ])('hands the posts to the cover number (%j) with the token, and answers when it ends and for how many services, without the number', async (body) => {
    answer(backendAnswers('post', backendPath, 200, OK));
    const response = await call(body);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(OK);
    expect(seenBackend[0]).toMatchObject({ path: backendPath, authorization: `Bearer ${REPORTER_TOKEN}`, body });
    expect(JSON.stringify(await response.clone().json())).not.toContain('07700');
  });

  it.each([
    ['a number that is not a UK mobile', { phone: '01632 960001', until: 'tonight' }],
    ['no number', { until: 'tonight' }],
    ['no until', { phone: '07700900123' }],
    ['an until that is not one of the three', { phone: '07700900123', until: 'forever' }],
    ['a date with until that is not date', { phone: '07700900123', until: 'tonight', date: '2026-11-05' }],
    ['until date with no date', { phone: '07700900123', until: 'date' }],
    ['a date that is not a date', { phone: '07700900123', until: 'date', date: '5 Nov' }],
    ['a field it does not take', { phone: '07700900123', until: 'tonight', tenant: 'trust-b' }],
  ])('refuses %s, 400, before the back end', async (_n, body) => {
    expect((await call(body)).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('passes on a back end refusal (a date too far ahead is a 400, a service not held the 404) and refuses an answer of another shape', async () => {
    answer(backendAnswers('post', backendPath, 400, { resourceType: 'OperationOutcome', issue: [{ code: 'invalid' }] }));
    expect((await call({ phone: '07700900123', until: 'tonight' })).status).toBe(400);
    answer(backendAnswers('post', backendPath, 404, {}));
    expect((await call({ phone: '07700900123', until: 'tonight' })).status).toBe(404);
    answer(backendAnswers('post', backendPath, 200, { ok: true }));
    expect((await call({ phone: '07700900123', until: 'tonight' })).status).toBe(502);
  });

  it('refuses a write with no CSRF token, and never answers not-built', async () => {
    expect((await call({ phone: '07700900123', until: 'tonight' }, { csrf: false })).status).toBe(403);
    answer(backendAnswers('post', backendPath, 200, OK));
    expect(await (await call({ phone: '07700900123', until: 'tonight' })).text()).not.toContain('not-built');
  });
});

describe('POST /api/bff/reporter/channel', () => {
  const call = (body: unknown, options: Parameters<typeof asReporter>[1] = {}) => asReporter(channel, { method: 'POST', body, ...options });

  it.each(['app', 'text', 'email'])('records %s with the reporter’s token', async (word) => {
    answer(backendAnswers('post', '/reporter/channel', 200, { channel: word }));
    const response = await call({ channel: word });
    expect(await response.json()).toEqual({ ok: true, channel: word });
    expect(seenBackend[0]).toMatchObject({ authorization: `Bearer ${REPORTER_TOKEN}`, body: { channel: word } });
  });

  it('refuses a channel that is not one of three, a field it does not take and a write with no CSRF token, before the back end', async () => {
    expect((await call({ channel: 'fax' })).status).toBe(400);
    expect((await call({ channel: 'text', deviceId: 'x' })).status).toBe(400);
    expect((await call({ channel: 'text' }, { csrf: false })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });

  it('passes on a back end refusal (email with no address on record is a 400), and refuses an answer that names no channel', async () => {
    answer(backendAnswers('post', '/reporter/channel', 400, { resourceType: 'OperationOutcome', issue: [{ code: 'invalid' }] }));
    expect((await call({ channel: 'email' })).status).toBe(400);
    answer(backendAnswers('post', '/reporter/channel', 200, {}));
    expect((await call({ channel: 'text' })).status).toBe(502);
  });
});

describe('POST /api/bff/reporter/services/[serviceId]/accept', () => {
  const call = (body: unknown, options: Parameters<typeof asReporter>[1] = {}) => asReporter(accept, { method: 'POST', body, params: { serviceId: 's1' }, ...options });

  it.each([true, false])('records the answer %s with the token', async (value) => {
    answer(backendAnswers('post', '/reporter/services/s1/accept', 200, { accepted: value }));
    expect(await (await call({ accept: value })).json()).toEqual({ accepted: value });
    expect(seenBackend[0]).toMatchObject({ authorization: `Bearer ${REPORTER_TOKEN}`, body: { accept: value } });
  });

  it('refuses an answer that is not a boolean, a field it does not take, a service that cannot be one, and no CSRF token, before the back end', async () => {
    expect((await call({ accept: 'yes' })).status).toBe(400);
    expect((await call({ accept: true, tenant: 'trust-b' })).status).toBe(400);
    expect((await asReporter(accept, { method: 'POST', body: { accept: true }, params: { serviceId: '../x' } })).status).toBe(404);
    expect((await call({ accept: true }, { csrf: false })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });

  it('answers the back end’s 404 as the one 404, and refuses an answer of another shape', async () => {
    answer(backendAnswers('post', '/reporter/services/s1/accept', 404, {}));
    expect((await call({ accept: true })).status).toBe(404);
    answer(backendAnswers('post', '/reporter/services/s1/accept', 200, { accepted: 'yes' }));
    expect((await call({ accept: true })).status).toBe(502);
  });
});

describe('POST /api/bff/reporter/bookings/[ref]/respond', () => {
  const PATH = '/reporter/bookings/4821/respond';
  const call = (body: unknown, options: Parameters<typeof asReporter>[1] = {}) => post(respond, body, { params: { ref: '4821' }, ...options });

  it('sends the decision and the reason to the booking by its reference, with the token and the key, and answers the status and when it was confirmed', async () => {
    answer(backendAnswers('post', PATH, 200, { status: 'confirmed', confirmedAt: '2026-10-30T14:19:00Z', internal: 'x' }));
    const response = await call({ decision: 'confirm' });
    expect(await response.json()).toEqual({ status: 'confirmed', confirmedAt: '2026-10-30T14:19:00Z' });
    expect(seenBackend[0]).toMatchObject({ path: PATH, authorization: `Bearer ${REPORTER_TOKEN}`, body: { decision: 'confirm' } });
    answer(backendAnswers('post', PATH, 200, { status: 'declined' }));
    expect(await (await call({ decision: 'decline', reason: 'full' })).json()).toEqual({ status: 'declined' });
    expect(seenBackend.at(-1)?.body).toEqual({ decision: 'decline', reason: 'full' });
  });

  it('passes the Idempotency-Key through', async () => {
    const { http, HttpResponse } = await import('msw');
    const { server } = await import('@/test/msw/server');
    let key: string | null = null;
    server.use(http.post(`${BACKEND}${PATH}`, ({ request }) => ((key = request.headers.get('idempotency-key')), HttpResponse.json({ status: 'confirmed' }))));
    await call({ decision: 'confirm' });
    expect(key).toBe(KEY);
  });

  it('answers a booking already answered (409) as a conflict, a booking that is not this reporter’s as the one 404', async () => {
    answer(backendAnswers('post', PATH, 409, { resourceType: 'OperationOutcome', issue: [{ code: 'conflict' }] }));
    expect((await call({ decision: 'confirm' })).status).toBe(409);
    answer(backendAnswers('post', PATH, 404, {}));
    expect((await call({ decision: 'confirm' })).status).toBe(404);
  });

  it.each([
    ['a decision that is neither confirm nor decline', { decision: 'maybe' }],
    ['a reason that is not one of the four', { decision: 'decline', reason: 'bored' }],
    ['a reason with a confirm', { decision: 'confirm', reason: 'full' }],
    ['a field it does not take', { decision: 'confirm', tenant: 'trust-b' }],
    ['no decision', {}],
  ])('refuses %s, 400, before the back end', async (_name, body) => {
    expect((await call(body)).status).toBe(400);
    expect(seenBackend).toEqual([]);
  });

  it('refuses a missing key, a reference that is not four digits, and no CSRF token, before the back end', async () => {
    expect((await call({ decision: 'confirm' }, { headers: { 'Idempotency-Key': '' } })).status).toBe(400);
    expect((await post(respond, { decision: 'confirm' }, { params: { ref: '48x1' } })).status).toBe(404);
    expect((await call({ decision: 'confirm' }, { csrf: false })).status).toBe(403);
    expect(seenBackend).toEqual([]);
  });

  it('refuses an answer that is not a status the screen knows', async () => {
    answer(backendAnswers('post', PATH, 200, { status: 'expired' }));
    expect((await call({ decision: 'confirm' })).status).toBe(502);
  });
});
