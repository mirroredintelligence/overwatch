// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND } from '@/test/fixtures/reporter';
import { cookiesMock, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { answer, backendAnswers, resetSeenBackend, seenBackend } from '@/test/preSessionCalls';
import { asReporter, KEY, REPORTER_TOKEN } from '@/test/reporterCalls';
import { OFFER_SAMPLE, SHIFT_SAMPLE, VISIT_SAMPLE } from '@/test/msw/handlers/practitioner';
import { GET as shiftRead } from './shift/route';
import { PUT as settingsWrite } from './settings/route';
import { GET as visitRead } from './visits/[id]/route';
import { POST as accept } from './visits/[id]/accept/route';
import { POST as decline } from './visits/[id]/decline/route';
import { POST as status } from './visits/[id]/status/route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The practitioner's BFF routes (DEC-1306 to DEC-1309), wired to the back end. Each carries the signed-in
// person's token and nothing that names a tenant, passes on only the fields a screen reads (the shape
// checked), takes only the fields it names (a position, a person or a tenant in a body is a 400), and
// answers what the back end answers: an id that is not the person's is the one 404.

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', `${BACKEND}/fhir`);
  vi.stubEnv('NODE_ENV', 'production');
  resetCookieWrites();
  cookiesMock.mockClear();
  resetSeenBackend();
});
afterEach(() => vi.unstubAllEnvs());

const ID = { id: 'offer-1' };
const put = (path: string, status: number, body: unknown) =>
  http.put(`${BACKEND}${path}`, async ({ request }) => {
    seenBackend.push({ method: 'PUT', path, host: request.headers.get('host'), authorization: request.headers.get('authorization'), body: await request.json().catch(() => undefined) });
    return HttpResponse.json(body as Record<string, unknown>, { status });
  });

describe('reads', () => {
  it('the shift is read with the person’s token, and only the parsed fields go on', async () => {
    answer(backendAnswers('get', '/practitioner/shift', 200, { ...SHIFT_SAMPLE, internal: 'x' }));
    const response = await asReporter(shiftRead, { path: '/api/bff/practitioner/shift' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(SHIFT_SAMPLE);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(seenBackend[0]?.authorization).toBe(`Bearer ${REPORTER_TOKEN}`);
  });

  it('a shift that is not the back end’s shape is a failure, not data', async () => {
    answer(backendAnswers('get', '/practitioner/shift', 200, { ...SHIFT_SAMPLE, location: 'always' }));
    const response = await asReporter(shiftRead, { path: '/api/bff/practitioner/shift' });
    expect(response.status).toBe(502);
  });

  it('an offer comes with no details, and an accepted visit with them', async () => {
    answer(backendAnswers('get', '/practitioner/visits/offer-1', 200, { ...OFFER_SAMPLE, address: 'x', contact: 'y' }));
    expect(await (await asReporter(visitRead, { path: '/api/bff/practitioner/visits/offer-1', params: ID })).json()).toEqual(OFFER_SAMPLE);
    answer(backendAnswers('get', '/practitioner/visits/visit-1', 200, VISIT_SAMPLE));
    expect(await (await asReporter(visitRead, { path: '/api/bff/practitioner/visits/visit-1', params: { id: 'visit-1' } })).json()).toEqual(VISIT_SAMPLE);
  });

  it('an id that is not one is the 404 and the back end is not asked', async () => {
    const response = await asReporter(visitRead, { path: '/api/bff/practitioner/visits/x', params: { id: '../../etc' } });
    expect(response.status).toBe(404);
    expect(seenBackend).toHaveLength(0);
  });

  it('the back end’s 404 and 403 are the one 404, and a 401 is the end of the session', async () => {
    for (const code of [404, 403]) {
      resetSeenBackend();
      answer(backendAnswers('get', '/practitioner/visits/offer-1', code, { resourceType: 'OperationOutcome', issue: [{ code: 'not-found' }] }));
      const response = await asReporter(visitRead, { path: '/api/bff/practitioner/visits/offer-1', params: ID });
      expect(response.status).toBe(404);
      expect(await response.json()).toMatchObject({ code: 'not-found' });
    }
    answer(backendAnswers('get', '/practitioner/visits/offer-1', 401, { resourceType: 'OperationOutcome', issue: [{ code: 'login' }] }));
    expect((await asReporter(visitRead, { path: '/api/bff/practitioner/visits/offer-1', params: ID })).status).toBe(401);
  });

  it('only a signed-in practitioner reads: another role is a 403 before the back end is asked', async () => {
    for (const role of ['lead', 'advisor', 'exec'] as const) {
      const response = await asReporter(shiftRead, { path: '/api/bff/practitioner/shift', role });
      expect(response.status).toBe(403);
    }
    expect(seenBackend).toHaveLength(0);
  });
});

describe('answers', () => {
  const call = (route: typeof accept, action: 'accept' | 'decline', body: unknown = {}, headers: Record<string, string> = { 'Idempotency-Key': KEY }) =>
    asReporter(route, { method: 'POST', path: `/api/bff/practitioner/visits/offer-1/${action}`, params: ID, body, headers });

  it.each([
    ['accept', accept],
    ['decline', decline],
  ] as const)('%s goes to the back end with its key and an empty body, and returns the id and state', async (action, route) => {
    answer(backendAnswers('post', `/practitioner/visits/offer-1/${action}`, 200, { id: 'offer-1', state: action === 'accept' ? 'accepted' : 'declined', more: 1 }));
    const response = await call(route, action);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ id: 'offer-1', state: action === 'accept' ? 'accepted' : 'declined' });
    expect(seenBackend[0]?.body).toEqual({});
  });

  it.each([
    ['accept', accept],
    ['decline', decline],
  ] as const)('%s refuses a call with no key, a body with a field, and a call with no CSRF token', async (action, route) => {
    expect((await call(route, action, {}, {})).status).toBe(400);
    expect((await call(route, action, { reason: 'x' })).status).toBe(400);
    expect((await call(route, action, { tenant: 'b' })).status).toBe(400);
    expect((await asReporter(route, { method: 'POST', path: '/x', params: ID, body: {}, headers: { 'Idempotency-Key': KEY }, csrf: false })).status).toBe(403);
    expect(seenBackend).toHaveLength(0);
  });

  it('a second person’s accept is the back end’s 409', async () => {
    answer(backendAnswers('post', '/practitioner/visits/offer-1/accept', 409, { resourceType: 'OperationOutcome', issue: [{ code: 'conflict' }] }));
    expect((await call(accept, 'accept')).status).toBe(409);
  });
});

describe('status', () => {
  const send = (body: unknown, headers: Record<string, string> = { 'Idempotency-Key': KEY }) =>
    asReporter(status, { method: 'POST', path: '/api/bff/practitioner/visits/offer-1/status', params: ID, body, headers });

  it('sends one of the four words, with an estimate in minutes only while on the way', async () => {
    answer(backendAnswers('post', '/practitioner/visits/offer-1/status', 200, { id: 'offer-1', state: 'on-my-way' }));
    expect((await send({ status: 'on-my-way', etaMinutes: 20 })).status).toBe(200);
    expect(seenBackend[0]?.body).toEqual({ status: 'on-my-way', etaMinutes: 20 });
    resetSeenBackend();
    answer(backendAnswers('post', '/practitioner/visits/offer-1/status', 200, { id: 'offer-1', state: 'arrived' }));
    expect((await send({ status: 'arrived' })).status).toBe(200);
    expect(seenBackend[0]?.body).toEqual({ status: 'arrived' });
  });

  it.each([
    ['a state that is not on the list', { status: 'accepted' }],
    ['a word that is not a state', { status: 'banana' }],
    ['no status', {}],
    ['an estimate with another status', { status: 'arrived', etaMinutes: 5 }],
    ['an estimate that is not minutes', { status: 'on-my-way', etaMinutes: '5' }],
    ['an estimate out of range', { status: 'on-my-way', etaMinutes: 500 }],
    ['an estimate that is not whole', { status: 'on-my-way', etaMinutes: 5.5 }],
    ['a position', { status: 'on-my-way', latitude: 51.1, longitude: -2.1 }],
    ['a tenant', { status: 'arrived', tenant: 'b' }],
  ])('refuses %s before the back end is asked', async (_name, body) => {
    expect((await send(body)).status).toBe(400);
    expect(seenBackend).toHaveLength(0);
  });

  it('refuses a call with no key', async () => {
    expect((await send({ status: 'arrived' }, {})).status).toBe(400);
  });
});

describe('settings', () => {
  const send = (body: unknown) => asReporter(settingsWrite, { method: 'PUT', path: '/api/bff/practitioner/settings', body });

  it('sends the status or the location or both, and returns what the back end saved', async () => {
    answer(put('/practitioner/settings', 200, { status: 'break', location: 'travel', more: 1 }));
    const response = await send({ status: 'break', location: 'travel' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'break', location: 'travel' });
    expect(seenBackend[0]?.body).toEqual({ status: 'break', location: 'travel' });
  });

  it('clears the status with null, and leaves the other answer out of the call', async () => {
    answer(put('/practitioner/settings', 200, { status: null, location: 'never' }));
    expect((await send({ status: null })).status).toBe(200);
    expect(seenBackend[0]?.body).toEqual({ status: null });
  });

  it.each([
    ['nothing', {}],
    ['an unknown status', { status: 'asleep' }],
    ['an unknown location', { location: 'always' }],
    ['a position', { location: 'travel', latitude: 51.1 }],
    ['a person', { status: 'break', practitionerId: 'p-2' }],
    ['a tenant', { location: 'never', tenant: 'b' }],
    ['not an object', [1]],
  ])('refuses %s before the back end is asked', async (_name, body) => {
    expect((await send(body)).status).toBe(400);
    expect(seenBackend).toHaveLength(0);
  });
});
