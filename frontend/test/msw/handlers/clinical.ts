import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { EXEC_BACKEND } from './exec';

const BACKEND_ROOT = EXEC_BACKEND.replace(/\/fhir$/, '');

// The back end's clinical routes (R13, U40, U41) for the clinical and advisor screens' tests. The queue
// is the one the back end lists: urgency, reason and the case it is about, and nothing more. The stand-in
// keeps the requests taken and advised in this test, and records each call.

export type SeenClinical = { method: string; path: string; idempotencyKey: string | null; body: unknown };
export const seenClinical: SeenClinical[] = [];
export const TAKEN_ELSEWHERE = 'req-4822';

const CLINICAL_CODE = 'https://diucs.example/CodeSystem/task-code';
const INPUT = 'https://diucs.example/CodeSystem/task-input';

const glance = (reference: string, news2: number) => [
  { url: `${INPUT}/case-reference`, valueString: reference },
  { url: `${INPUT}/age-band`, valueCode: '80+' },
  { url: `${INPUT}/need`, valueCode: 'frailty' },
  { url: `${INPUT}/need`, valueCode: 'fall-no-injury' },
  { url: `${INPUT}/case-urgency`, valueCode: 'within-2-hrs' },
  { url: `${INPUT}/news2`, valueInteger: news2 },
];

type Ext = { url: string; [key: string]: unknown };
const task = (id: string, caseId: string, status: string, authoredOn: string, extension: Ext[]) => ({
  resourceType: 'Task',
  id,
  status,
  code: { coding: [{ system: CLINICAL_CODE, code: 'clinical-advice' }] },
  focus: { reference: `ServiceRequest/${caseId}` },
  authoredOn,
  extension,
});

// What the back end lists (R13, DEC-774): each Task carries the case's glance (number, age band, needs,
// urgency, NEWS2), and never the postcode, the district or a person's id.
export const QUEUE_TASKS = [
  task('req-4821', 'case-4821', 'requested', '2026-10-23T13:11:00+00:00', [
    { url: `${INPUT}/urgency`, valueCode: 'now' },
    { url: `${INPUT}/why`, valueCode: 'borderline-criteria' },
    ...glance('4821', 2),
  ]),
  task(TAKEN_ELSEWHERE, 'case-4822', 'requested', '2026-10-23T13:05:00+00:00', [
    { url: `${INPUT}/urgency`, valueCode: 'within-15-min' },
    { url: `${INPUT}/why`, valueCode: 'unsure-of-urgency' },
    ...glance('4822', 5),
  ]),
];

/** A request the signed-in clinician holds (Mine). */
export const MINE_TASK = task('req-5001', 'case-5001', 'in-progress', '2026-10-23T13:00:00+00:00', [
  { url: `${INPUT}/urgency`, valueCode: 'now' },
  { url: `${INPUT}/why`, valueCode: 'other' },
  ...glance('5001', 3),
  { url: `${INPUT}/returns-at`, valueDateTime: '2026-10-23T13:29:30Z' },
]);

/** A request the clinician advised on (Done): the list carries the advice, not the note. */
export const DONE_TASK = task('req-5002', 'case-5002', 'completed', '2026-10-23T12:40:00+00:00', [
  { url: `${INPUT}/urgency`, valueCode: 'within-15-min' },
  { url: `${INPUT}/why`, valueCode: 'borderline-criteria' },
  ...glance('5002', 4),
  { url: `${INPUT}/advice-choice`, valueCode: 'use-another-service' },
  { url: `${INPUT}/advised-at`, valueDateTime: '2026-10-23T12:50:00Z' },
]);

/** A taken request whose case the back end could not read: the Task has no case glance. */
export const UNREADABLE_TASK = task('req-5003', 'case-5003', 'in-progress', '2026-10-23T13:00:00+00:00', [
  { url: `${INPUT}/urgency`, valueCode: 'now' },
  { url: `${INPUT}/why`, valueCode: 'other' },
  { url: `${INPUT}/returns-at`, valueDateTime: '2026-10-23T13:29:30Z' },
]);

/** A request the asking advisor reads once advised: the choice, the reason, the note and when. */
export const ADVISED_TASK = task('req-9001', 'case-4821', 'completed', '2026-10-23T13:10:00+00:00', [
  { url: `${INPUT}/urgency`, valueCode: 'now' },
  { url: `${INPUT}/why`, valueCode: 'borderline-criteria' },
  ...glance('4821', 2),
  { url: `${INPUT}/advice-choice`, valueCode: 'go-ahead' },
  { url: `${INPUT}/advice-reason`, valueCode: 'within-criteria-on-judgement' },
  { url: `${INPUT}/advice-note`, valueString: 'Phone the family first.' },
  { url: `${INPUT}/advised-at`, valueDateTime: '2026-10-23T13:15:00Z' },
]);

export const TASKS_BY_ID: Record<string, unknown> = Object.fromEntries(
  [...QUEUE_TASKS, MINE_TASK, DONE_TASK, UNREADABLE_TASK, ADVISED_TASK].map((item) => [item.id, item]),
);

/** The tasks each list status gives. */
export const LISTS: Record<string, unknown[]> = {
  requested: QUEUE_TASKS,
  'in-progress': [MINE_TASK],
  completed: [DONE_TASK],
};


// What the back end answers for what the advisor saw and the way to reach the advisor (W9G: `GET
// /clinical/requests/{id}/seen` and `/advisor-contact`, at the back end's root). The shapes are the back end's
// (clinical_mapping.seen_json and contact_json). Only the clinician who holds a request reads either: any other id
// is the one 404 of an id that is nowhere.
export const SEEN_SHOWN = {
  state: 'shown',
  shownAt: '2026-10-23T13:13:20Z',
  options: 2,
  noneFitted: false,
  lines: [
    { service: 'UCR West', shownAs: 'option', status: 'accepting', statusText: 'Accepting', figure: '4', age: '9 min old', stale: false, why: null, criteriaVersion: 3 },
    { service: 'Hospital at home', shownAs: 'option', status: 'over-capacity', statusText: 'Over capacity', figure: '+2', age: '14 min old', stale: false, why: null, criteriaVersion: 3 },
    { service: 'Ward B', shownAs: 'option', status: 'accepting', statusText: 'Accepting', figure: '5', age: '2 hrs 10 min old', stale: true, why: null, criteriaVersion: 3 },
    { service: 'UCR East', shownAs: 'not-suitable', status: 'not-accepting', statusText: 'Not accepting', figure: null, age: '3 min old', stale: false, why: 'Not accepting', criteriaVersion: 3 },
  ],
};
export const SEEN_NONE_FITTED = {
  state: 'shown',
  shownAt: '2026-10-23T13:13:20Z',
  options: 0,
  noneFitted: true,
  lines: [
    { service: 'UCR East', shownAs: 'not-suitable', status: 'not-accepting', statusText: 'Not accepting', figure: null, age: '3 min old', stale: false, why: 'Not accepting', criteriaVersion: 3 },
    { service: 'Ward B', shownAs: 'not-suitable', status: 'accepting', statusText: 'Accepting', figure: '5', age: '1 min old', stale: false, why: 'Outside its criteria', criteriaVersion: 3 },
  ],
};
export const SEEN_NO_DISPLAY = { state: 'none', shownAt: null, options: 0, noneFitted: false, lines: [] };
export const SEEN_UNREADABLE = { state: 'unreadable', shownAt: null, options: 0, noneFitted: false, lines: [] };
export const WORK_PHONE_CONTACT = { available: true, via: 'work-phone', phone: '07700 900123', name: 'Sample Advisor' };
export const LINE_CONTACT = { available: true, via: 'advisor-line', phone: '01305 900000', name: null };
export const NO_CONTACT = { available: false, via: null, phone: null, name: null };

const SEEN_BY_ID: Record<string, unknown> = {
  'req-5001': SEEN_SHOWN,
  'req-5002': SEEN_SHOWN,
  'req-5006': SEEN_NONE_FITTED,
  'req-5007': SEEN_NO_DISPLAY,
  'req-5008': SEEN_UNREADABLE,
};
const CONTACT_BY_ID: Record<string, unknown> = {
  'req-5001': WORK_PHONE_CONTACT,
  'req-5006': LINE_CONTACT,
  'req-5007': NO_CONTACT,
};
const notFound = () =>
  HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'The requested resource was not found.' }] }, { status: 404 });

export function resetClinicalBackend() {
  seenClinical.length = 0;
}

const conflict = () =>
  HttpResponse.json(
    { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict', diagnostics: 'taken' }] },
    { status: 409 },
  );

export const clinicalBackendHandlers = [
  // The advice request is a POST /Task; the queue is a GET. Both are on this stand-in.
  http.get(`${EXEC_BACKEND}/Task`, (({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get('code') !== 'clinical-advice') return undefined;
    seenClinical.push({ method: 'GET', path: `/Task?${url.search.slice(1)}`, idempotencyKey: null, body: undefined });
    const tasks = LISTS[url.searchParams.get('status') ?? ''];
    if (tasks === undefined) return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid', diagnostics: 'status' }] }, { status: 400 });
    return HttpResponse.json({ resourceType: 'Bundle', type: 'searchset', total: tasks.length, entry: tasks.map((resource) => ({ resource })) });
  }) as HttpResponseResolver),
  // One request (W7A, DEC-774): any id that is not a clinical request falls through to the booking stand-in.
  http.get(`${EXEC_BACKEND}/Task/:id`, (({ params }) => {
    const found = TASKS_BY_ID[String(params.id)];
    if (found === undefined) {
      // A request id that is nowhere is the back end's 404; any other id is a booking's.
      if (!String(params.id).startsWith('req-')) return undefined;
      seenClinical.push({ method: 'GET', path: `/Task/${String(params.id)}`, idempotencyKey: null, body: undefined });
      return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'no such task' }] }, { status: 404 });
    }
    seenClinical.push({ method: 'GET', path: `/Task/${String(params.id)}`, idempotencyKey: null, body: undefined });
    return HttpResponse.json(found);
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
  http.get(`${BACKEND_ROOT}/clinical/requests/:id/seen`, (({ params }) => {
    const id = String(params.id);
    seenClinical.push({ method: 'GET', path: `/clinical/requests/${id}/seen`, idempotencyKey: null, body: undefined });
    if (id === 'req-fail') return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'exception', diagnostics: 'Internal error' }] }, { status: 500 });
    const found = SEEN_BY_ID[id];
    return found === undefined ? notFound() : HttpResponse.json(found);
  }) as HttpResponseResolver),
  http.get(`${BACKEND_ROOT}/clinical/requests/:id/advisor-contact`, (({ params }) => {
    const id = String(params.id);
    seenClinical.push({ method: 'GET', path: `/clinical/requests/${id}/advisor-contact`, idempotencyKey: null, body: undefined });
    if (id === 'req-fail') return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'exception', diagnostics: 'Internal error' }] }, { status: 500 });
    const found = CONTACT_BY_ID[id];
    return found === undefined ? notFound() : HttpResponse.json(found);
  }) as HttpResponseResolver),
  // The clinician's own presence and the count (W7A, DEC-780): at the back end's root, not under /fhir.
  http.get(`${BACKEND_ROOT}/clinical/presence`, (() => {
    seenClinical.push({ method: 'GET', path: '/clinical/presence', idempotencyKey: null, body: undefined });
    return HttpResponse.json({ presence: 'busy', available: 2 });
  }) as HttpResponseResolver),
  http.put(`${BACKEND_ROOT}/clinical/presence`, (async ({ request }) => {
    const body = await request.json().catch(() => undefined);
    seenClinical.push({ method: 'PUT', path: '/clinical/presence', idempotencyKey: null, body });
    return HttpResponse.json(body ?? {});
  }) as HttpResponseResolver),
  http.get(`${BACKEND_ROOT}/clinical/available`, (() => {
    seenClinical.push({ method: 'GET', path: '/clinical/available', idempotencyKey: null, body: undefined });
    return HttpResponse.json({ available: 2 });
  }) as HttpResponseResolver),
];

// The browser's own calls to the BFF, for the component tests: what the browser sent, and the BFF's
// answers in the shapes the BFF gives. A component test asserts on these, never on the back end.
export const seenBff: SeenClinical[] = [];

const GLANCE = { ageBand: '80+', needs: ['frailty', 'fall-no-injury'], caseUrgency: 'within-2-hrs' };
const item = (id: string, caseId: string, reference: string, news2: number, extra: Record<string, unknown>) => ({
  id,
  status: 'requested',
  urgency: 'now',
  why: 'borderline-criteria',
  requestedAt: '2026-10-23T13:11:00Z',
  caseId,
  glance: { caseReference: reference, ...GLANCE, news2 },
  returnsAt: null,
  advice: null,
  service: null,
  ...extra,
});

/** What the BFF answers for a request (lib/clinical/task.ts). */
export const QUEUE_ITEMS = [
  item('req-4821', 'case-4821', '4821', 2, {}),
  item(TAKEN_ELSEWHERE, 'case-4822', '4822', 5, { urgency: 'within-15-min', why: 'unsure-of-urgency', requestedAt: '2026-10-23T13:05:00Z' }),
];
export const MINE_ITEMS = [item('req-5001', 'case-5001', '5001', 3, { status: 'in-progress', why: 'other', returnsAt: '2026-10-23T13:29:30Z' })];
export const DONE_ITEMS = [
  item('req-5002', 'case-5002', '5002', 4, {
    status: 'completed',
    urgency: 'within-15-min',
    advice: { choice: 'use-another-service', reason: null, note: null, at: '2026-10-23T12:50:00Z' },
  }),
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
    const tab = new URL(request.url).searchParams.get('tab') ?? 'waiting';
    return HttpResponse.json({ items: tab === 'mine' ? MINE_ITEMS : tab === 'done' ? DONE_ITEMS : QUEUE_ITEMS });
  }) as HttpResponseResolver),
  http.get('/api/bff/clinical/presence', (async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ presence: 'busy', available: 2 });
  }) as HttpResponseResolver),
  http.put('/api/bff/clinical/presence', (async ({ request }) => {
    const body = await recorded(request);
    return HttpResponse.json(body ?? {});
  }) as HttpResponseResolver),
  http.get('/api/bff/clinical/requests/:id/advisor-contact', (async ({ request, params }) => {
    await recorded(request);
    const id = String(params.id);
    if (id === 'req-lost') return HttpResponse.json({ code: 'not-found', message: 'We could not find that.' }, { status: 404 });
    if (id === 'req-fail') return HttpResponse.json({ code: 'unavailable' }, { status: 503 });
    const found = CONTACT_BY_ID[id];
    return found === undefined ? HttpResponse.json({ code: 'not-found' }, { status: 404 }) : HttpResponse.json({ contact: found });
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

/** The back end's `POST /fhir/Task` for a clinical advice request (R13), recorded for the route tests. */
export const requestBodies: unknown[] = [];
export const clinicalRequestHandler = http.post(`${EXEC_BACKEND}/Task`, (async ({ request }) => {
  const body = await request.json().catch(() => undefined);
  requestBodies.push(body);
  return HttpResponse.json(
    { resourceType: 'Task', id: 'req-9001', businessStatus: { coding: [{ code: 'requested' }] }, output: [{ valueInteger: 2 }] },
    { status: 201 },
  );
}) as HttpResponseResolver);
