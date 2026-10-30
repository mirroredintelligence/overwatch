import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { DECISION_OPEN, OVERVIEW, QUEUE, SCOPE_ENTRIES } from '@/test/fixtures/registration';
import type { ScopeEntry } from '@/lib/registration/types';

// The BFF's registration routes, as the browser sees them (W28). Each request the browser makes is
// kept, so a test can assert what was sent and what was not sent. The list is reset per test.

export type SeenRequest = {
  method: string;
  path: string;
  search: string;
  body: unknown;
  csrf: string | null;
  idempotencyKey: string | null;
};

export const seenRegistrationRequests: SeenRequest[] = [];

let scope: ScopeEntry[] = SCOPE_ENTRIES.map((entry) => ({ ...entry }));

export function resetRegistrationRequests() {
  seenRegistrationRequests.length = 0;
  scope = SCOPE_ENTRIES.map((entry) => ({ ...entry }));
}

async function record(request: Request): Promise<SeenRequest> {
  const url = new URL(request.url);
  const text = request.method === 'GET' ? '' : await request.text();
  let body: unknown = undefined;
  if (text !== '') {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }
  const seen: SeenRequest = {
    method: request.method,
    path: url.pathname,
    search: url.search,
    body,
    csrf: request.headers.get('X-CSRF-Token'),
    idempotencyKey: request.headers.get('Idempotency-Key'),
  };
  seenRegistrationRequests.push(seen);
  return seen;
}

const json = (body: unknown, status = 200) =>
  HttpResponse.json(body as Record<string, unknown>, { status, headers: { 'Cache-Control': 'no-store' } });

export const registrationHandlers = [
  http.get('/api/bff/scope', (async ({ request }) => {
    await record(request);
    return json({ entries: scope });
  }) as HttpResponseResolver),

  http.post('/api/bff/scope', (async ({ request }) => {
    const seen = await record(request);
    const body = seen.body as { name: string; category: string; flag: ScopeEntry['flag']; reason?: string };
    const serviceId = `s${scope.length + 1}`;
    scope.push({
      serviceId,
      name: body.name,
      category: body.category,
      flag: body.flag,
      registrationState: 'not-invited',
      ...(body.reason ? { reason: body.reason } : {}),
    });
    return json({ serviceId }, 201);
  }) as HttpResponseResolver),

  http.get('/api/bff/registrations', (async ({ request }) => {
    await record(request);
    return json(QUEUE);
  }) as HttpResponseResolver),

  http.get('/api/bff/registrations/:id', (async ({ request }) => {
    await record(request);
    return json(OVERVIEW);
  }) as HttpResponseResolver),
];

// W29: the check steps. The decision read is what the Decide and Go live steps show; a test that
// needs another answer overrides it with server.use().

export const registrationStepHandlers = [
  http.post('/api/bff/registrations/:id/callback', (async ({ request }) => {
    await record(request);
    return json({ result: 'confirmed', callbackConfirmed: true });
  }) as HttpResponseResolver),

  http.post('/api/bff/registrations/:id/scope', (async ({ request }) => {
    await record(request);
    return json({ flag: 'in-pilot' });
  }) as HttpResponseResolver),

  http.get('/api/bff/registrations/:id/decision', (async ({ request }) => {
    await record(request);
    return json(DECISION_OPEN);
  }) as HttpResponseResolver),

  http.post('/api/bff/registrations/:id/decision', (async ({ request }) => {
    await record(request);
    return json({ status: 'approved' });
  }) as HttpResponseResolver),

  http.post('/api/bff/registrations/:id/go-live', (async ({ request }) => {
    await record(request);
    return json({ status: 'live' });
  }) as HttpResponseResolver),
];
