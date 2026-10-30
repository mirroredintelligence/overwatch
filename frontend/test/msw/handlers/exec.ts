import { http, HttpResponse, type HttpResponseResolver } from 'msw';

// The back end's alert, preferences and week-summary routes (R12, U33 to U35), for the exec
// screens' tests. The stand-in keeps the saved Subscription in memory, so a PUT then a GET reads
// what was written, and records every request it sees.

export const EXEC_BACKEND = 'http://backend.test/fhir';
export const SUBSCRIBER_ID = 'pr-0042';

export type SeenBackend = { method: string; path: string; ifMatch: string | null; idempotencyKey: string | null; body: unknown };
export const seenBackend: SeenBackend[] = [];

const SETTING = 'https://diucs.example/CodeSystem/alert-preferences';

// What the back end sends for a practitioner who has never saved (the rule book's defaults).
const NEVER_SAVED = {
  resourceType: 'Subscription',
  id: SUBSCRIBER_ID,
  meta: { versionId: '1' },
  status: 'active',
  reason: 'Alert preferences of a shift lead or an executive',
  criteria: 'alert-preferences',
  channel: { type: 'message' },
  extension: [
    { url: `${SETTING}/kind`, valueCode: 'service-closed' },
    { url: `${SETTING}/kind`, valueCode: 'over-capacity' },
    { url: `${SETTING}/kind`, valueCode: 'not-updated' },
    { url: `${SETTING}/kind`, valueCode: 'system-pressure' },
    { url: `${SETTING}/not-updated-hours`, valueInteger: 2 },
    { url: `${SETTING}/ack-minutes`, valueInteger: 15 },
    { url: `${SETTING}/quiet-critical-only`, valueBoolean: true },
    { url: `${SETTING}/daily-summary`, valueBoolean: true },
    { url: `${SETTING}/weekly-summary`, valueBoolean: false },
  ],
};

let saved: Record<string, unknown> | null = null;

export function resetExecBackend() {
  seenBackend.length = 0;
  saved = null;
}

export function savedSubscription() {
  return saved;
}

async function body(request: Request): Promise<unknown> {
  return request.json().catch(() => undefined);
}

const TASK_CODE = 'https://diucs.example/CodeSystem/task-code';
const ALERT_KIND = 'https://diucs.example/CodeSystem/alert-kind';
const ALERT_STATUS = 'https://diucs.example/CodeSystem/alert-status';

/** Open alerts for the caller, as the back end lists them (R12, GET /fhir/Task). */
export const OPEN_ALERT_TASKS = [
  {
    resourceType: 'Task',
    id: 'al-1',
    status: 'requested',
    code: { coding: [{ system: TASK_CODE, code: 'acknowledge-alert' }] },
    businessStatus: { coding: [{ system: ALERT_STATUS, code: 'new' }] },
    owner: { reference: `Practitioner/${SUBSCRIBER_ID}` },
    authoredOn: '2026-10-23T13:04:00+00:00',
    focus: { reference: 'HealthcareService/svc-ucr-west' },
    executionPeriod: { end: '2026-10-23T13:19:00+00:00' },
    extension: [{ url: ALERT_KIND, valueCode: 'not-updated' }],
  },
];

export const execBackendHandlers = [
  http.get(`${EXEC_BACKEND}/Task`, (({ request }) => {
    const url = new URL(request.url);
    seenBackend.push({ method: 'GET', path: `/Task?${url.search.slice(1)}`, ifMatch: null, idempotencyKey: null, body: undefined });
    return HttpResponse.json({ resourceType: 'Bundle', type: 'searchset', total: OPEN_ALERT_TASKS.length, entry: OPEN_ALERT_TASKS.map((resource) => ({ resource })) });
  }) as HttpResponseResolver),
  http.post(`${EXEC_BACKEND}/Task/:id/$acknowledge`, (async ({ request, params }) => {
    seenBackend.push({
      method: 'POST',
      path: `/Task/${String(params.id)}/$acknowledge`,
      ifMatch: null,
      idempotencyKey: request.headers.get('Idempotency-Key'),
      body: undefined,
    });
    return HttpResponse.json({ resourceType: 'Task', id: String(params.id), businessStatus: { coding: [{ code: 'acknowledged' }] } });
  }) as HttpResponseResolver),
  http.post(`${EXEC_BACKEND}/Task/:id/$snooze`, (async ({ request, params }) => {
    seenBackend.push({
      method: 'POST',
      path: `/Task/${String(params.id)}/$snooze`,
      ifMatch: null,
      idempotencyKey: request.headers.get('Idempotency-Key'),
      body: undefined,
    });
    return HttpResponse.json({
      resourceType: 'Parameters',
      parameter: [
        { name: 'alertId', valueString: String(params.id) },
        { name: 'escalationDueAt', valueDateTime: '2026-10-23T14:19:00Z' },
      ],
    });
  }) as HttpResponseResolver),
  http.get(`${EXEC_BACKEND}/Subscription`, (() => {
    seenBackend.push({ method: 'GET', path: '/Subscription', ifMatch: null, idempotencyKey: null, body: undefined });
    const resource = saved ?? NEVER_SAVED;
    return HttpResponse.json(
      { resourceType: 'Bundle', type: 'searchset', total: 1, entry: [{ resource }] },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  }) as HttpResponseResolver),
  http.put(`${EXEC_BACKEND}/Subscription/:id`, (async ({ request, params }) => {
    const payload = await body(request);
    seenBackend.push({
      method: 'PUT',
      path: `/Subscription/${String(params.id)}`,
      ifMatch: request.headers.get('If-Match'),
      idempotencyKey: request.headers.get('Idempotency-Key'),
      body: payload,
    });
    const version = String(Date.now());
    saved = { ...(payload as Record<string, unknown>), id: String(params.id), meta: { versionId: version } };
    return HttpResponse.json(saved, { headers: { ETag: `W/"${version}"`, 'Cache-Control': 'no-store' } });
  }) as HttpResponseResolver),
];
