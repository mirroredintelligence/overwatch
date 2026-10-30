import { http, HttpResponse } from 'msw';
import { OVERVIEW_SHIFT_LEAD, SERVICE_REABLEMENT, SERVICE_UCR_EAST, SERVICE_VIRTUAL_WARD } from '@/test/fixtures/lead';

// The shift lead's BFF routes, for component tests (W17, W18). The default answers are the "ShiftLead"
// sample. A test that needs another answer uses server.use(...) in the test itself.

export type SeenLeadPost = {
  path: string;
  csrf: string | null;
  idempotencyKey: string | null;
  body: unknown;
};

/** Every lead POST this test file's handlers saw, newest last. */
export const seenLeadPosts: SeenLeadPost[] = [];

export function resetLeadPosts() {
  seenLeadPosts.length = 0;
}

const NO_STORE = { 'Cache-Control': 'no-store' };

/** The back end's origin: the admin and identity routes sit beside the /fhir base (DEC-087). */
export const BACKEND_ROOT = 'http://backend.test';

/** The services the lead may choose from (the BFF's list, W18). */
export const SERVICE_CHOICES = [
  { id: SERVICE_VIRTUAL_WARD, name: 'Virtual ward' },
  { id: SERVICE_UCR_EAST, name: 'UCR East' },
  { id: SERVICE_REABLEMENT, name: 'Reablement' },
];

async function recorded(request: Request, path: string) {
  let body: unknown;
  try {
    body = await request.clone().json();
  } catch {
    body = undefined;
  }
  seenLeadPosts.push({
    path,
    csrf: request.headers.get('x-csrf-token'),
    idempotencyKey: request.headers.get('idempotency-key'),
    body,
  });
}

/** The flags on the open list, as the BFF maps them (W42). */
export const FLAG_CHOICES = [
  { id: 'flag-1', serviceId: SERVICE_UCR_EAST, serviceName: 'UCR East', reason: 'out-of-range-twice', summary: 'The figure was out of its usual range twice.' },
  { id: 'flag-2', serviceId: SERVICE_REABLEMENT, serviceName: 'Reablement', reason: 'many-changes', summary: 'The figure changed many times in a short time.' },
];

export const leadHandlers = [
  http.get('/api/bff/lead/overview', () => HttpResponse.json(OVERVIEW_SHIFT_LEAD, { headers: NO_STORE })),
  http.get('/api/bff/lead/services', () => HttpResponse.json({ services: SERVICE_CHOICES }, { headers: NO_STORE })),
  http.post('/api/bff/lead/services', async ({ request }) => {
    await recorded(request, '/api/bff/lead/services');
    return HttpResponse.json({ serviceId: 's-new-1' }, { status: 201, headers: NO_STORE });
  }),
  http.post('/api/bff/lead/reporters/number', async ({ request }) => {
    await recorded(request, '/api/bff/lead/reporters/number');
    return HttpResponse.json({ numberEnding: '0456' }, { status: 200, headers: NO_STORE });
  }),
  http.post('/api/bff/lead/services/:id/test-prompt', async ({ request, params }) => {
    await recorded(request, `/api/bff/lead/services/${String(params.id)}/test-prompt`);
    return HttpResponse.json({ state: 'sent' }, { status: 202, headers: NO_STORE });
  }),
  http.get('/api/bff/lead/services/:id', ({ params }) =>
    HttpResponse.json({ id: String(params.id), name: 'UCR East' }, { headers: NO_STORE }),
  ),
  http.post('/api/bff/lead/services/:id/suspend', async ({ request, params }) => {
    await recorded(request, `/api/bff/lead/services/${String(params.id)}/suspend`);
    return HttpResponse.json(
      { since: '2026-10-30T14:20:00Z', expiredRequests: 2, notified: true },
      { status: 200, headers: NO_STORE },
    );
  }),
  http.post('/api/bff/lead/services/:id/resume', async ({ request, params }) => {
    await recorded(request, `/api/bff/lead/services/${String(params.id)}/resume`);
    return HttpResponse.json({ status: 'active', nextDueAt: '2026-10-30T16:00:00Z' }, { status: 200, headers: NO_STORE });
  }),
  http.post('/api/bff/lead/people/remove', async ({ request }) => {
    await recorded(request, '/api/bff/lead/people/remove');
    return HttpResponse.json({ removed: true }, { status: 200, headers: NO_STORE });
  }),
  http.get('/api/bff/lead/flags', () =>
    HttpResponse.json({ counts: { toCheck: FLAG_CHOICES.length, checked: 0 }, items: FLAG_CHOICES }, { headers: NO_STORE }),
  ),
  http.post('/api/bff/lead/flags/:id', async ({ request, params }) => {
    await recorded(request, `/api/bff/lead/flags/${String(params.id)}`);
    return HttpResponse.json({ flagId: String(params.id), outcome: 'accepted' }, { status: 200, headers: NO_STORE });
  }),
  http.post('/api/bff/lead/services/:id/remind', async ({ request, params }) => {
    await recorded(request, `/api/bff/lead/services/${String(params.id)}/remind`);
    return HttpResponse.json({ state: 'sent' }, { status: 202, headers: NO_STORE });
  }),
];
