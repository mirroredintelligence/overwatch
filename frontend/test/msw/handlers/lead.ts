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
  http.post('/api/bff/lead/services/:id/remind', async ({ request, params }) => {
    await recorded(request, `/api/bff/lead/services/${String(params.id)}/remind`);
    return HttpResponse.json({ state: 'sent' }, { status: 202, headers: NO_STORE });
  }),
];
