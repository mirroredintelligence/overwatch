import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { BACKEND_ROOT } from '@/test/fixtures/links';

// Registration (W23 to W27). Two stand-ins: the back end's answers (identity and the registration
// routes, as R10 and U25 built them) and the BFF's answers at the browser's own paths, which the
// browser components and the page tests use. Sample values only. Every request the browser or the
// BFF sends is kept, so a test can assert the body it sent.

/** The identity routes as the back end answers them. */
export type BackendReply = { status: number; body: unknown; headers?: Record<string, string> };

/** What the back end is asked to do next. Tests set these; resetRegistrationHandlers puts them back. */
export const backendIdentity: {
  code: BackendReply;
  verify: BackendReply;
} = {
  code: { status: 202, body: { accepted: true, resendAfterSeconds: 60 } },
  verify: { status: 200, body: { verified: true } },
};

/** Every request the BFF sent to the back end's identity routes, newest last. */
export const seenBackendIdentity: { path: string; host: string | null; body: unknown; headers: Record<string, string> }[] = [];

/** Every request the browser sent to the BFF's registration routes, newest last. */
export const seenBffRegistration: { method: string; path: string; body: unknown; csrf: string | null }[] = [];

/** The BFF's answer for the sign-in code requests the browser makes. */
export const bffRegistration: {
  codeSend: BackendReply;
  verify: BackendReply;
} = {
  codeSend: { status: 202, body: { accepted: true, resendAfterSeconds: 60 } },
  verify: { status: 200, body: { registrationId: 'REG-SAMPLE-1' } },
};

export function resetRegistrationHandlers() {
  seenBackendIdentity.length = 0;
  seenBffRegistration.length = 0;
  backendIdentity.code = { status: 202, body: { accepted: true, resendAfterSeconds: 60 } };
  backendIdentity.verify = { status: 200, body: { verified: true } };
  bffRegistration.codeSend = { status: 202, body: { accepted: true, resendAfterSeconds: 60 } };
  bffRegistration.verify = { status: 200, body: { registrationId: 'REG-SAMPLE-1' } };
}

function reply({ status, body, headers }: BackendReply) {
  return HttpResponse.json(body as Record<string, unknown>, {
    status,
    headers: { 'Cache-Control': 'no-store', ...headers },
  });
}

async function jsonBody(request: Request): Promise<unknown> {
  return (await request.json().catch(() => null)) as unknown;
}

/** The back end's identity routes (the same origin the link routes use, beside /fhir). */
export const backendIdentityHandlers = [
  http.post(`${BACKEND_ROOT}/identity/code`, (async ({ request }) => {
    seenBackendIdentity.push({
      path: '/identity/code',
      host: request.headers.get('host'),
      body: await jsonBody(request),
      headers: Object.fromEntries(request.headers.entries()),
    });
    return reply(backendIdentity.code);
  }) as HttpResponseResolver),
  http.post(`${BACKEND_ROOT}/identity/code/verify`, (async ({ request }) => {
    seenBackendIdentity.push({
      path: '/identity/code/verify',
      host: request.headers.get('host'),
      body: await jsonBody(request),
      headers: Object.fromEntries(request.headers.entries()),
    });
    return reply(backendIdentity.verify);
  }) as HttpResponseResolver),
];

/** The BFF's registration routes, as the browser sees them. */
export const bffRegistrationHandlers = [
  http.post('/api/bff/identity/code', (async ({ request }) => {
    seenBffRegistration.push({
      method: 'POST',
      path: '/api/bff/identity/code',
      body: await jsonBody(request),
      csrf: request.headers.get('x-csrf-token'),
    });
    return reply(bffRegistration.codeSend);
  }) as HttpResponseResolver),
  http.post('/api/bff/identity/code/verify', (async ({ request }) => {
    seenBffRegistration.push({
      method: 'POST',
      path: '/api/bff/identity/code/verify',
      body: await jsonBody(request),
      csrf: request.headers.get('x-csrf-token'),
    });
    return reply(bffRegistration.verify);
  }) as HttpResponseResolver),
];

/** The BFF's session answer (CSRF token included) that the registration pages read before a save. */
export const sessionAnswer = { role: 'reporter', services: [] as string[], sub: 'person-sample-1', csrfToken: 'csrf-sample-token' };

/** The registration the BFF reads at its GET and the answer to a step save (W54 and later). */
export const bffRegistrationState: { view: unknown; read: BackendReply; step: BackendReply } = {
  view: {
    id: 'REG-SAMPLE-1',
    status: 'draft',
    invitation: { serviceName: 'UCR West', organisationName: 'Sample Community Trust', odsCode: 'RSA01' },
    steps: {},
  },
  read: { status: 200, body: {} },
  step: { status: 200, body: { status: 'draft' } },
};

/** Every step save the browser made, newest last. */
export const seenStepSaves: { id: string; step: string; body: unknown; csrf: string | null }[] = [];

export function resetStepSaves() {
  seenStepSaves.length = 0;
  seenSubmits.length = 0;
  reviewState.reply = reviewDefault();
  bffRegistrationState.step = { status: 200, body: { status: 'draft' } };
}

export const bffRegistrationStepHandlers = [
  http.get('/api/bff/session', (() =>
    HttpResponse.json(sessionAnswer, { headers: { 'Cache-Control': 'no-store' } })) as HttpResponseResolver),
  http.get('/api/bff/registrations/:id', (({ params }) => {
    if (bffRegistrationState.read.status !== 200) return reply(bffRegistrationState.read);
    return HttpResponse.json({ ...(bffRegistrationState.view as object), id: String(params.id) }, { headers: { 'Cache-Control': 'no-store' } });
  }) as HttpResponseResolver),
  http.put('/api/bff/registrations/:id/steps/:step', (async ({ request, params }) => {
    seenStepSaves.push({
      id: String(params.id),
      step: String(params.step),
      body: await jsonBody(request),
      csrf: request.headers.get('x-csrf-token'),
    });
    return reply(bffRegistrationState.step);
  }) as HttpResponseResolver),
];

/** The postcode lookup the BFF answers (W24). The default lists three sample addresses. */
export const addressState: { lookup: BackendReply } = {
  lookup: {
    status: 200,
    body: [
      { id: 'addr-1', label: 'Sample House, Dorchester, DT4 8XX' },
      { id: 'addr-2', label: 'Sample Flat, Dorchester, DT4 8XX' },
      { id: 'addr-3', label: 'Sample Lodge, Dorchester, DT4 8XX' },
    ],
  },
};

/** Every postcode the browser looked up, newest last (normalised as the BFF received them). */
export const seenAddressRequests: string[] = [];

export function resetAddressRequests() {
  seenAddressRequests.length = 0;
}

export const bffAddressHandlers = [
  http.get('/api/bff/addresses', (({ request }) => {
    seenAddressRequests.push(new URL(request.url).searchParams.get('postcode') ?? '');
    return reply(addressState.lookup);
  }) as HttpResponseResolver),
];

/** The review the BFF gives the applicant (W26): one row per section, each complete or needing attention. */
function reviewDefault(): BackendReply {
  return {
    status: 200,
    body: {
      sections: [
        { key: 'organisation', status: 'complete', summary: 'Sample Community Trust · NHS trust · Sample Person' },
        { key: 'location', status: 'complete', summary: 'Fixed site · Sample Ward · Mon to Fri 08:00 to 18:00' },
        { key: 'service', status: 'complete', summary: 'UCR West · Urgent community response · refer by phone and SystmOne' },
        { key: 'reporting', status: 'complete', summary: 'Referrals in the next 2 hrs · 0 to 8 · every 2 hrs · by text' },
        { key: 'api', status: 'complete', summary: 'No API' },
      ],
    },
  };
}

export const reviewState: { reply: BackendReply } = { reply: reviewDefault() };

/** Every submit the browser made, newest last. */
export const seenSubmits: { id: string; csrf: string | null }[] = [];

/** The services of the signed-in reporter (W26's My services). */
export const minePayload = {
  services: [
    { id: 'REG-SAMPLE-1', serviceName: 'UCR West', state: 'active', detail: 'Reporting every 2 hrs by text' },
    { id: 'REG-SAMPLE-2', serviceName: 'UCR East', state: 'pending-approval', detail: 'Submitted 23 Oct' },
    { id: 'REG-SAMPLE-3', serviceName: 'Ward 4', state: 'review-due', detail: 'Criteria review due 30 Oct' },
  ],
};

export const bffRegistrationReviewHandlers = [
  http.get('/api/bff/registrations/:id/review', (() => reply(reviewState.reply)) as HttpResponseResolver),
  http.post('/api/bff/registrations/:id/submit', (({ request, params }) => {
    seenSubmits.push({ id: String(params.id), csrf: request.headers.get('x-csrf-token') });
    return HttpResponse.json({ status: 'submitted' }, { status: 200 });
  }) as HttpResponseResolver),
  http.get('/api/bff/registrations/mine', (() => HttpResponse.json(minePayload, { headers: { 'Cache-Control': 'no-store' } })) as HttpResponseResolver),
];

// The BFF's fixed paths (mine, review, submit) come before the registration's /:id read, so a path
// such as /registrations/mine is answered by its own handler, not as an id.
export const registrationHandlers = [
  ...backendIdentityHandlers,
  ...bffRegistrationHandlers,
  ...bffRegistrationReviewHandlers,
  ...bffRegistrationStepHandlers,
  ...bffAddressHandlers,
];
