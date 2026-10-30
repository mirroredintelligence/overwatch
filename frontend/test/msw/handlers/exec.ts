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

export const execBackendHandlers = [
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
