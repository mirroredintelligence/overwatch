import { http, HttpResponse } from 'msw';
import { ONE_TIME_CODE, RAW_SETTINGS, VIEW_LOG, VIEW_OVERVIEW, VIEW_TICKETS, VIEW_VERSIONS } from '@/test/fixtures/tenantAdmin';

// The tenant administrator's BFF routes for component tests (TEN-076): the answers are what the BFF gives
// the browser (test/fixtures/tenantAdmin.ts, VIEW_*). A write is recorded with the CSRF token and the
// idempotency key it carried and the body it sent. A test that needs another answer uses server.use(...).

export type SeenAdminWrite = { method: string; path: string; csrf: string | null; key: string | null; body: unknown };

export const seenAdminWrites: SeenAdminWrite[] = [];
export function resetAdminWrites() {
  seenAdminWrites.length = 0;
}

const NO_STORE = { 'Cache-Control': 'no-store' };

async function recorded(request: Request) {
  let body: unknown;
  try {
    body = await request.clone().json();
  } catch {
    body = undefined;
  }
  seenAdminWrites.push({
    method: request.method,
    path: new URL(request.url).pathname,
    csrf: request.headers.get('x-csrf-token'),
    key: request.headers.get('idempotency-key'),
    body,
  });
}

export const tenantAdminHandlers = [
  http.get('/api/bff/tenant/overview', () => HttpResponse.json(VIEW_OVERVIEW, { headers: NO_STORE })),
  http.get('/api/bff/tenant/settings', () => HttpResponse.json(RAW_SETTINGS, { headers: NO_STORE })),
  http.get('/api/bff/tenant/config/versions', () => HttpResponse.json(VIEW_VERSIONS, { headers: NO_STORE })),
  http.get('/api/bff/tenant/config/versions/:n', ({ params }) => {
    const one = VIEW_VERSIONS.versions.find((v) => String(v.version) === params.n);
    return one ? HttpResponse.json(one, { headers: NO_STORE }) : HttpResponse.json({ code: 'not-found' }, { status: 404, headers: NO_STORE });
  }),
  http.get('/api/bff/tenant/access-log', () => HttpResponse.json(VIEW_LOG, { headers: NO_STORE })),
  http.get('/api/bff/tenant/support-tickets', () => HttpResponse.json(VIEW_TICKETS, { headers: NO_STORE })),
  http.post('/api/bff/tenant/config/drafts', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ version: 4, changedKeys: ['pressureWatchFrom'], clinicalKeys: ['pressureWatchFrom'], approvalsRequired: 2 }, { status: 201, headers: NO_STORE });
  }),
  http.post('/api/bff/tenant/config/versions/:n/approval', async ({ request, params }) => {
    await recorded(request);
    return HttpResponse.json({ version: Number(params.n), status: 'pending-approval', approvals: 1, approvalsRequired: 2 }, { headers: NO_STORE });
  }),
  http.put('/api/bff/tenant/contacts', async ({ request }) => {
    await recorded(request);
    return new HttpResponse(null, { status: 204, headers: NO_STORE });
  }),
  http.post('/api/bff/tenant/channels', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ id: 'ch-new' }, { status: 201, headers: NO_STORE });
  }),
  http.put('/api/bff/tenant/channels/:id', async ({ request, params }) => {
    await recorded(request);
    return HttpResponse.json({ id: String(params.id) }, { headers: NO_STORE });
  }),
  http.put('/api/bff/tenant/retention', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ stored: 8 }, { headers: NO_STORE });
  }),
  http.put('/api/bff/tenant/directory', async ({ request }) => {
    await recorded(request);
    return new HttpResponse(null, { status: 204, headers: NO_STORE });
  }),
  http.put('/api/bff/tenant/role-mappings', async ({ request }) => {
    await recorded(request);
    return new HttpResponse(null, { status: 204, headers: NO_STORE });
  }),
  http.post('/api/bff/tenant/support-tickets/:id/approval', async ({ request, params }) => {
    await recorded(request);
    const ticket = VIEW_TICKETS.tickets.find((t) => t.id === params.id) ?? VIEW_TICKETS.tickets[0]!;
    return HttpResponse.json({ ticket: { ...ticket, state: 'approved' }, code: ONE_TIME_CODE, codeExpiresAt: '2026-10-30T13:00:00Z' }, { headers: NO_STORE });
  }),
  http.post('/api/bff/tenant/support-tickets/:id/refusal', async ({ request, params }) => {
    await recorded(request);
    const ticket = VIEW_TICKETS.tickets.find((t) => t.id === params.id) ?? VIEW_TICKETS.tickets[0]!;
    return HttpResponse.json({ ...ticket, state: 'refused' }, { headers: NO_STORE });
  }),
  http.delete('/api/bff/tenant/support-tickets/:id/access', async ({ request, params }) => {
    await recorded(request);
    const ticket = VIEW_TICKETS.tickets.find((t) => t.id === params.id) ?? VIEW_TICKETS.tickets[0]!;
    return HttpResponse.json({ ...ticket, state: 'revoked' }, { headers: NO_STORE });
  }),
];
