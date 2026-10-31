// @vitest-environment node
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Role } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { clinicalBackendHandlers, resetClinicalBackend, seenClinical } from '@/test/msw/handlers/clinical';
import { EXEC_BACKEND, execBackendHandlers } from '@/test/msw/handlers/exec';
import { requestAs } from '@/test/requests';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

async function get(ref: string, id: string, role: Role = 'advisor') {
  return GET(await requestAs(TENANTS.A, role, { path: `/api/bff/cases/${ref}/clinical-requests/${id}` }), { params: Promise.resolve({ ref, id }) });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetClinicalBackend();
  server.use(...clinicalBackendHandlers, ...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/cases/[ref]/clinical-requests/[id]', () => {
  it('reads the request from the back end and says waiting while nobody has taken it', async () => {
    const response = await get('case-4821', 'req-4821');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ state: 'waiting' });
    expect(seenClinical.at(-1)?.path).toBe('/Task/req-4821');
  });

  it('says taken, and when the request returns to the queue, while a clinician holds it', async () => {
    server.use(http.get(`${EXEC_BACKEND}/Task/req-9001`, (() => HttpResponse.json({ ...(clinicalTask('in-progress')) })) as HttpResponseResolver));
    const body = await (await get('case-4821', 'req-9001')).json();
    expect(body).toEqual({ state: 'taken', returnsAt: '2026-10-23T13:29:30Z' });
  });

  it('gives the advice: the choice, the reason, the note and when it was given, once advised', async () => {
    const response = await get('case-4821', 'req-9001');
    expect(await response.json()).toEqual({
      state: 'advised',
      advice: 'go-ahead',
      reason: 'within-criteria-on-judgement',
      note: 'Phone the family first.',
      advisedAt: '2026-10-23T13:15:00Z',
    });
  });

  it('is a 404 when the request is about another case than the one in the path', async () => {
    expect((await get('case-9999', 'req-9001')).status).toBe(404);
  });

  it('is the same 404 for a request that is nowhere or another advisor\'s, and never says which', async () => {
    const response = await get('case-4821', 'req-0000');
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
  });

  it('answers a failed back-end read as a failure, never as waiting', async () => {
    server.use(http.get(`${EXEC_BACKEND}/Task/req-9001`, (() => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'exception', diagnostics: 'x' }] }, { status: 503 })) as HttpResponseResolver));
    expect((await get('case-4821', 'req-9001')).status).toBe(503);
  });

  it('refuses a role that may not ask for advice', async () => {
    expect((await get('case-4821', 'req-9001', 'reporter')).status).toBe(403);
  });
});

function clinicalTask(status: string) {
  const base = clinicalTaskBase();
  return { ...base, status, extension: [...(base.extension as unknown[]), { url: 'https://diucs.example/CodeSystem/task-input/returns-at', valueDateTime: '2026-10-23T13:29:30Z' }] };
}

function clinicalTaskBase() {
  return {
    resourceType: 'Task',
    id: 'req-9001',
    status: 'requested',
    code: { coding: [{ code: 'clinical-advice' }] },
    focus: { reference: 'ServiceRequest/case-4821' },
    authoredOn: '2026-10-23T13:10:00+00:00',
    extension: [
      { url: 'https://diucs.example/CodeSystem/task-input/urgency', valueCode: 'now' },
      { url: 'https://diucs.example/CodeSystem/task-input/why', valueCode: 'other' },
    ],
  };
}

describe('the service under consideration on the read (KI-768)', () => {
  it('answers the name of the service the advisor asked about, on a waiting, taken and advised request', async () => {
    const withService = (status: string, more: unknown[] = []) => {
      const base = clinicalTask(status);
      return { ...base, extension: [...(base.extension as unknown[]), { url: 'https://diucs.example/CodeSystem/task-input/service', valueString: 'UCR West' }, ...more] };
    };
    for (const [status, more] of [
      ['requested', []],
      ['in-progress', []],
      ['completed', [{ url: 'https://diucs.example/CodeSystem/task-input/advice-choice', valueCode: 'go-ahead' }]],
    ] as const) {
      server.use(http.get(`${EXEC_BACKEND}/Task/req-9001`, (() => HttpResponse.json(withService(status, [...more]))) as HttpResponseResolver));
      const body = (await (await get('case-4821', 'req-9001')).json()) as { service?: string };
      expect(body.service).toBe('UCR West');
    }
  });

  it('answers no service when the request names none', async () => {
    server.use(http.get(`${EXEC_BACKEND}/Task/req-9001`, (() => HttpResponse.json(clinicalTask('requested'))) as HttpResponseResolver));

    expect(await (await get('case-4821', 'req-9001')).json()).toEqual({ state: 'waiting' });
  });
});
