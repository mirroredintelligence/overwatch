import { http, HttpResponse } from 'msw';
import { AUDIT_4821, OVERVIEW_SHIFT_LEAD, SERVICE_REABLEMENT, SERVICE_UCR_EAST, SERVICE_VIRTUAL_WARD } from '@/test/fixtures/lead';

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

/** The phones the lead's services report from, as the BFF maps them (W43). Last digits only. */
export const PHONE_CHOICES = [
  {
    phoneEnding: '777',
    role: 'Duty manager',
    services: [
      { id: SERVICE_VIRTUAL_WARD, name: 'Virtual ward' },
      { id: SERVICE_UCR_EAST, name: 'UCR East' },
      { id: SERVICE_REABLEMENT, name: 'Reablement' },
      { id: 's-other', name: 'Community beds' },
    ],
    channel: 'text',
    lastSeen: '2026-10-30T09:21:00Z',
  },
  {
    phoneEnding: '456',
    role: 'Team lead',
    services: [{ id: SERVICE_REABLEMENT, name: 'Reablement' }],
    channel: 'email',
    lastSeen: '2026-10-30T08:02:00Z',
  },
];

/** The reporter invitations and their set-up steps, as the BFF maps them (W43). */
export const INVITATION_CHOICES = [
  {
    id: 'inv-1',
    serviceName: 'UCR West',
    role: 'Duty manager',
    steps: { invited: true, numberChecked: true, channelChosen: true, installed: true, notificationsOn: false, pinSet: false, firstReport: false },
    invitedAt: '2026-10-30T09:00:00Z',
    lastSeen: '2026-10-30T09:21:00Z',
    firstReportAt: null,
  },
  {
    id: 'inv-2',
    serviceName: 'Reablement',
    role: 'Team lead',
    steps: { invited: true, numberChecked: true, channelChosen: true, installed: true, notificationsOn: true, pinSet: true, firstReport: true },
    invitedAt: '2026-10-29T16:00:00Z',
    lastSeen: '2026-10-30T10:12:00Z',
    firstReportAt: '2026-10-30T10:12:00Z',
  },
];

export const leadHandlers = [
  http.get('/api/bff/lead/audit/:ref', ({ params }) =>
    params.ref === AUDIT_4821.reference
      ? HttpResponse.json(AUDIT_4821, { headers: NO_STORE })
      : HttpResponse.json({ code: 'not-found' }, { status: 404, headers: NO_STORE }),
  ),
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
  http.get('/api/bff/lead/phones', () => HttpResponse.json({ phones: PHONE_CHOICES }, { headers: NO_STORE })),
  http.get('/api/bff/lead/invitations', () => HttpResponse.json({ items: INVITATION_CHOICES }, { headers: NO_STORE })),
  http.post('/api/bff/lead/invitations', async ({ request }) => {
    await recorded(request, '/api/bff/lead/invitations');
    return HttpResponse.json({ invitationId: 'inv-3', numberEnding: '0123', expiresAt: '2026-11-01T09:00:00Z' }, { status: 201, headers: NO_STORE });
  }),
  http.post('/api/bff/lead/invitations/:id/resend', async ({ request, params }) => {
    await recorded(request, `/api/bff/lead/invitations/${String(params.id)}/resend`);
    return HttpResponse.json({ state: 'sent' }, { status: 202, headers: NO_STORE });
  }),
  http.post('/api/bff/lead/invitations/:id/switch-to-text', async ({ request, params }) => {
    await recorded(request, `/api/bff/lead/invitations/${String(params.id)}/switch-to-text`);
    return HttpResponse.json({ state: 'switched' }, { status: 200, headers: NO_STORE });
  }),
  http.post('/api/bff/lead/services/:id/move', async ({ request, params }) => {
    await recorded(request, `/api/bff/lead/services/${String(params.id)}/move`);
    return HttpResponse.json({ moveId: 'move-1' }, { status: 201, headers: NO_STORE });
  }),
  http.post('/api/bff/lead/services/:id/remind', async ({ request, params }) => {
    await recorded(request, `/api/bff/lead/services/${String(params.id)}/remind`);
    return HttpResponse.json({ state: 'sent' }, { status: 202, headers: NO_STORE });
  }),
];
