import { http, HttpResponse } from 'msw';
import {
  VIEW_AUDIT,
  VIEW_DETAIL_PROVISIONING,
  VIEW_SUPPORT_TICKETS,
  VIEW_TENANTS_OPERATOR,
  viewTicket,
  rawTicket,
} from '@/test/fixtures/operator';

// The operator console's BFF routes for component tests (TEN-083): the answers are what the BFF gives the
// console (test/fixtures/operator.ts, VIEW_*). The CSRF token is the console's own, from its own session
// route. A write is recorded with the token and the key it carried and the body it sent.

export const OPERATOR_SAMPLE_CSRF = 'operator-csrf-sample-token';

export type SeenOperatorWrite = { method: string; path: string; csrf: string | null; key: string | null; body: unknown };
export const seenOperatorWrites: SeenOperatorWrite[] = [];
export function resetOperatorWrites() {
  seenOperatorWrites.length = 0;
}

const NO_STORE = { 'Cache-Control': 'no-store' };

async function recorded(request: Request) {
  let body: unknown;
  try {
    body = await request.clone().json();
  } catch {
    body = undefined;
  }
  seenOperatorWrites.push({ method: request.method, path: new URL(request.url).pathname, csrf: request.headers.get('x-csrf-token'), key: request.headers.get('idempotency-key'), body });
}

const ok = (body: unknown, status = 200) => HttpResponse.json(body as Record<string, unknown>, { status, headers: NO_STORE });

export const operatorHandlers = [
  http.get('/api/bff/platform/session', () =>
    ok({ role: 'platform-operator', accountRef: 'ops-0123456789abcdef0123456789abcdef', expiresAt: '2026-10-30T10:00:00Z', permissions: ['tenants:list'], csrfToken: OPERATOR_SAMPLE_CSRF }),
  ),
  http.get('/api/bff/platform/tenants', () => ok(VIEW_TENANTS_OPERATOR)),
  http.get('/api/bff/platform/tenants/:id', () => ok(VIEW_DETAIL_PROVISIONING)),
  http.get('/api/bff/platform/audit', ({ request }) => {
    const after = new URL(request.url).searchParams.get('afterSeq');
    return after === '3' ? ok({ entries: [{ seq: 4, action: 'tenant-activated', principalRef: 'ops-0123456789abcdef0123456789abcdef', tenantId: 'trust-b', accessId: null, snapshot: { status: 'active' }, at: '2026-10-22T09:00:00Z' }], next: null }) : ok(VIEW_AUDIT);
  }),
  http.get('/api/bff/platform/audit/verification', () => ok({ intact: true })),
  http.get('/api/bff/platform/support-tickets', () => ok(VIEW_SUPPORT_TICKETS)),
  http.get('/api/bff/platform/support-tickets/:id', ({ params }) => ok(VIEW_SUPPORT_TICKETS.tickets.find((t) => t.id === params.id) ?? VIEW_SUPPORT_TICKETS.tickets[0])),
  http.put('/api/bff/platform/tenants/:id', async ({ request }) => { await recorded(request); return ok({ created: true, recorded: true }, 201); }),
  http.put('/api/bff/platform/tenants/:id/host', async ({ request }) => { await recorded(request); return ok({ recorded: true }); }),
  http.post('/api/bff/platform/tenants/:id/numbers', async ({ request }) => { await recorded(request); return ok({ recorded: true }, 201); }),
  http.post('/api/bff/platform/tenants/:id/numbers/tested', async ({ request }) => { await recorded(request); return ok({ recorded: true }); }),
  http.put('/api/bff/platform/tenants/:id/references', async ({ request }) => { await recorded(request); return ok({ references: ['dsa_ref'], recorded: true }); }),
  http.post('/api/bff/platform/tenants/:id/directory/verification', async ({ request }) => { await recorded(request); return ok({ recorded: true }); }),
  http.post('/api/bff/platform/tenants/:id/admin-invitation', async ({ request }) => { await recorded(request); return ok({ expiresAt: '2026-11-01T09:00:00Z', recorded: true }, 201); }),
  http.post('/api/bff/platform/tenants/:id/activation', async ({ request }) => { await recorded(request); return ok({ recorded: true }); }),
  http.post('/api/bff/platform/tenants/:id/suspension', async ({ request }) => { await recorded(request); return ok({ mode: 'read-only', recorded: true }); }),
  http.delete('/api/bff/platform/tenants/:id/suspension', async ({ request }) => { await recorded(request); return ok({ servicesPrompted: 3, servicesAnnounced: 1, resumedAgain: false, recorded: true }); }),
  http.post('/api/bff/platform/tenants/:id/offboarding', async ({ request }) => { await recorded(request); return ok({ startedAt: '2026-10-30T09:00:00Z', noticeEndsAt: '2026-11-29T09:00:00Z', recorded: true }); }),
  http.post('/api/bff/platform/tenants/:id/support-tickets', async ({ request }) => { await recorded(request); return ok(viewTicket(rawTicket()), 201); }),
  http.post('/api/bff/platform/support-tickets/:id/cancellation', async ({ request }) => { await recorded(request); return ok({ ...viewTicket(rawTicket()), state: 'cancelled' }); }),
  http.post('/api/bff/platform/support-tickets/:id/access', async ({ request }) => {
    await recorded(request);
    return ok({ ticket: { ...viewTicket(rawTicket({ id: 'tkt-2', tenantId: 'trust-c', state: 'opened', openedAt: '2026-10-30T09:00:00Z' })) }, access: { expiresAt: '2026-10-30T10:00:00Z' } });
  }),
  http.delete('/api/bff/platform/support-tickets/:id/access', async ({ request }) => { await recorded(request); return ok({ ...viewTicket(rawTicket({ state: 'ended' })) }); }),
];
