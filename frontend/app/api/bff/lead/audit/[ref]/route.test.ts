// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { BACKEND_ROOT } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ctx = (ref: string) => ({ params: Promise.resolve({ ref }) });

const BACK_END_REPLAY = {
  reference: '4821',
  shown_at: '2026-10-23T13:13:20Z',
  chain_ok: true,
  rows: [
    { service_name: 'UCR West', status: 'Accepting', value_text: '4', data_age_text: '9 min old', criteria_version: 3 },
    { service_name: 'Reablement', status: 'Not updated', value_text: 'No figure', data_age_text: '2 hrs 10 min old', criteria_version: null },
  ],
  timeline: [{ at: '2026-10-23T13:12:00Z', label: 'Case 4821 opened' }],
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('GET /api/bff/lead/audit/[ref]', () => {
  it('answers the replay in the BFF shape, with the decision time as decisionAt', async () => {
    server.use(http.get(`${BACKEND_ROOT}/admin/audit/4821`, () => HttpResponse.json(BACK_END_REPLAY)));
    const response = await GET(await leadRequest('https://app.test/api/bff/lead/audit/4821', 'lead'), ctx('4821'));
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(await response.json()).toEqual({
      reference: '4821',
      decisionAt: '2026-10-23T13:13:20Z',
      chainOk: true,
      shown: [
        { serviceName: 'UCR West', status: 'Accepting', value: '4', age: '9 min old' },
        { serviceName: 'Reablement', status: 'Not updated', value: 'No figure', age: '2 hrs 10 min old' },
      ],
      criteriaVersions: [{ serviceName: 'UCR West', version: 3 }],
      timeline: [{ at: '2026-10-23T13:12:00Z', label: 'Case 4821 opened' }],
    });
  });

  it('asks the back end with cache no-store, so no copy of the replay is kept', async () => {
    server.use(http.get(`${BACKEND_ROOT}/admin/audit/4821`, () => HttpResponse.json(BACK_END_REPLAY)));
    const spy = vi.spyOn(globalThis, 'fetch');
    await GET(await leadRequest('https://app.test/api/bff/lead/audit/4821', 'lead'), ctx('4821'));
    const call = spy.mock.calls.find(([url]) => String(url).includes('/admin/audit/4821'));
    expect(call?.[1]).toMatchObject({ cache: 'no-store' });
  });

  it('answers 404 for a reference the back end does not know, and 404 for a refusal too (the same words)', async () => {
    server.use(http.get(`${BACKEND_ROOT}/admin/audit/9999`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'x' }] }, { status: 404 })));
    const unknown = await GET(await leadRequest('https://app.test/api/bff/lead/audit/9999', 'lead'), ctx('9999'));
    expect(unknown.status).toBe(404);
    server.use(http.get(`${BACKEND_ROOT}/admin/audit/5555`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'forbidden', diagnostics: 'y' }] }, { status: 403 })));
    const refused = await GET(await leadRequest('https://app.test/api/bff/lead/audit/5555', 'lead'), ctx('5555'));
    expect(refused.status).toBe(404);
    expect(await refused.text()).toBe(await unknown.text());
  });

  it('answers 404 for a malformed reference, without calling the back end', async () => {
    let called = false;
    server.use(http.get(`${BACKEND_ROOT}/admin/audit/:ref`, () => { called = true; return HttpResponse.json({}); }));
    const response = await GET(await leadRequest('https://app.test/api/bff/lead/audit/x', 'lead'), ctx('../admin'));
    expect(response.status).toBe(404);
    expect(called).toBe(false);
  });

  it('answers 403 to an advisor', async () => {
    expect((await GET(await leadRequest('https://app.test/api/bff/lead/audit/4821', 'advisor'), ctx('4821'))).status).toBe(403);
  });
});
