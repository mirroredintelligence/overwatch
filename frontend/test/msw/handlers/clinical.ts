import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { EXEC_BACKEND } from './exec';

// The back end's clinical routes (R13, U40, U41) for the clinical and advisor screens' tests. The queue
// is the one the back end lists: urgency, reason and the case it is about, and nothing more. The stand-in
// keeps the requests taken and advised in this test, and records each call.

export type SeenClinical = { method: string; path: string; idempotencyKey: string | null; body: unknown };
export const seenClinical: SeenClinical[] = [];
export const TAKEN_ELSEWHERE = 'req-4822';

const CLINICAL_CODE = 'https://diucs.example/CodeSystem/task-code';
const INPUT = 'https://diucs.example/CodeSystem/task-input';

export const QUEUE_TASKS = [
  {
    resourceType: 'Task',
    id: 'req-4821',
    status: 'requested',
    code: { coding: [{ system: CLINICAL_CODE, code: 'clinical-advice' }] },
    focus: { reference: 'ServiceRequest/case-4821' },
    authoredOn: '2026-10-23T13:11:00+00:00',
    extension: [
      { url: `${INPUT}/urgency`, valueCode: 'now' },
      { url: `${INPUT}/why`, valueCode: 'borderline-criteria' },
    ],
  },
  {
    resourceType: 'Task',
    id: TAKEN_ELSEWHERE,
    status: 'requested',
    code: { coding: [{ system: CLINICAL_CODE, code: 'clinical-advice' }] },
    focus: { reference: 'ServiceRequest/case-4822' },
    authoredOn: '2026-10-23T13:05:00+00:00',
    extension: [
      { url: `${INPUT}/urgency`, valueCode: 'within-15-min' },
      { url: `${INPUT}/why`, valueCode: 'unsure-of-urgency' },
    ],
  },
];

export function resetClinicalBackend() {
  seenClinical.length = 0;
}

const conflict = () =>
  HttpResponse.json(
    { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict', diagnostics: 'taken' }] },
    { status: 409 },
  );

export const clinicalBackendHandlers = [
  http.get(`${EXEC_BACKEND}/Task`, (({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get('code') !== 'clinical-advice') return undefined;
    seenClinical.push({ method: 'GET', path: `/Task?${url.search.slice(1)}`, idempotencyKey: null, body: undefined });
    return HttpResponse.json({ resourceType: 'Bundle', type: 'searchset', total: QUEUE_TASKS.length, entry: QUEUE_TASKS.map((resource) => ({ resource })) });
  }) as HttpResponseResolver),
  http.post(`${EXEC_BACKEND}/Task/:id/$take`, (({ request, params }) => {
    seenClinical.push({ method: 'POST', path: `/Task/${String(params.id)}/$take`, idempotencyKey: request.headers.get('Idempotency-Key'), body: undefined });
    if (params.id === TAKEN_ELSEWHERE) return conflict();
    return HttpResponse.json({ resourceType: 'Task', id: String(params.id), businessStatus: { coding: [{ code: 'in-progress' }] } });
  }) as HttpResponseResolver),
  http.post(`${EXEC_BACKEND}/Task/:id/$advise`, (async ({ request, params }) => {
    const body = await request.json().catch(() => undefined);
    seenClinical.push({ method: 'POST', path: `/Task/${String(params.id)}/$advise`, idempotencyKey: request.headers.get('Idempotency-Key'), body });
    return HttpResponse.json({ resourceType: 'Task', id: String(params.id), businessStatus: { coding: [{ code: 'completed' }] } });
  }) as HttpResponseResolver),
  http.put(`${EXEC_BACKEND}/clinical/presence`, (async ({ request }) => {
    const body = await request.json().catch(() => undefined);
    seenClinical.push({ method: 'PUT', path: '/clinical/presence', idempotencyKey: null, body });
    return HttpResponse.json(body ?? {});
  }) as HttpResponseResolver),
  http.get(`${EXEC_BACKEND}/clinical/available`, (() => {
    seenClinical.push({ method: 'GET', path: '/clinical/available', idempotencyKey: null, body: undefined });
    return HttpResponse.json({ available: 2 });
  }) as HttpResponseResolver),
];

// The browser's own calls to the BFF, for the component tests: what the browser sent, and the BFF's
// answers in the shapes the BFF gives. A component test asserts on these, never on the back end.
export const seenBff: SeenClinical[] = [];

export const QUEUE_ITEMS = [
  { id: 'req-4821', urgency: 'now', why: 'borderline-criteria', requestedAt: '2026-10-23T13:11:00Z', status: 'requested', caseId: 'case-4821' },
  { id: TAKEN_ELSEWHERE, urgency: 'within-15-min', why: 'unsure-of-urgency', requestedAt: '2026-10-23T13:05:00Z', status: 'requested', caseId: 'case-4822' },
];

async function recorded(request: Request, params: Record<string, string | readonly string[] | undefined> = {}): Promise<unknown> {
  const body = await request.json().catch(() => undefined);
  seenBff.push({ method: request.method, path: new URL(request.url).pathname, idempotencyKey: request.headers.get('Idempotency-Key'), body });
  void params;
  return body;
}

export function resetClinicalBff() {
  seenBff.length = 0;
}

export const clinicalBffHandlers = [
  http.get('/api/bff/clinical/requests', (async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ items: QUEUE_ITEMS });
  }) as HttpResponseResolver),
  http.put('/api/bff/clinical/presence', (async ({ request }) => {
    const body = await recorded(request);
    return HttpResponse.json(body ?? {});
  }) as HttpResponseResolver),
  http.post('/api/bff/clinical/requests/:id/take', (async ({ request, params }) => {
    await recorded(request);
    if (params.id === TAKEN_ELSEWHERE) return HttpResponse.json({ code: 'conflict', message: 'That changed while you were working. Reload and try again.' }, { status: 409 });
    return HttpResponse.json({ id: String(params.id), status: 'in-progress' });
  }) as HttpResponseResolver),
  http.post('/api/bff/clinical/requests/:id/advice', (async ({ request, params }) => {
    await recorded(request);
    return HttpResponse.json({ id: String(params.id), status: 'completed' });
  }) as HttpResponseResolver),
];
