import { http, HttpResponse } from 'msw';
import { BOARD_A } from '@/test/fixtures/board';
import { OPTIONS_VIEW } from '@/test/fixtures/options';

// Browser-facing stubs for the advisor screens (W10 to W16, W50): the BFF routes a client component
// calls, answered from fixtures. Every request a test makes must match a handler (test/setup.ts).

export const CSRF_TOKEN = 'csrf-token-for-tests-only-0000000000000000000';
export const CASE_ID = '4821';

// A case as the BFF reads it before anything is recorded (W11). The ETag is the one the back end
// sends for a case (DEC-398): If-Match is required on a PUT, and its value is not compared.
export const CASE_ETAG = 'W/"1"';
export const BLANK_CASE = {
  id: CASE_ID,
  referrerType: null,
  ageBand: null,
  postcode: null,
  needs: [],
  urgency: null,
  scores: [],
  openedAt: null,
  etag: CASE_ETAG,
};

/** Every POST /api/bff/cases this file's handlers saw, newest last. */
export const seenCaseCreates: Request[] = [];
/** Every PUT /api/bff/cases/[ref] this file's handlers saw. */
export const seenCasePuts: { url: string; ifMatch: string | null; body: unknown }[] = [];

export function resetSeenAdvisorRequests() {
  seenCaseCreates.length = 0;
  seenCasePuts.length = 0;
  PATHWAYS_BACKEND_CALLS.length = 0;
  seenOptionsReads.length = 0;
}

const caseHandlers = [
  http.get('/api/bff/cases/:ref', () => HttpResponse.json(BLANK_CASE)),
  http.put('/api/bff/cases/:ref', async ({ request }) => {
    seenCasePuts.push({
      url: request.url,
      ifMatch: request.headers.get('if-match'),
      body: await request.json(),
    });
    return HttpResponse.json({ ...BLANK_CASE, etag: CASE_ETAG });
  }),
];

// The Pathways Dx lookup (R16 through the BFF). Codes are fixture values, not clinical text.
export const PATHWAYS_RESULTS = [
  { code: 'PD-101', display: 'Sample Dx one' },
  { code: 'PD-102', display: 'Sample Dx two' },
];
/** The query of every BFF lookup this file saw, in order. */
export const PATHWAYS_BACKEND_CALLS: string[] = [];

const pathwaysHandlers = [
  http.get('/api/bff/terminology/pathways-dx', ({ request }) => {
    const q = new URL(request.url).searchParams.get('q') ?? '';
    PATHWAYS_BACKEND_CALLS.push(q);
    return HttpResponse.json(PATHWAYS_RESULTS);
  }),
];

/** Every GET /api/bff/cases/[ref]/options this file's handlers saw (one per page load, W13). */
export const seenOptionsReads: string[] = [];

export const CRITERIA_VIEW = {
  accepts: 'Falls without injury · Frailty · Age 18+ · Postcodes DT1 to DT4 · 08:00 to 20:00',
  excludes: 'Suspected fracture · Head injury on anticoagulants · Needs IV therapy',
  version: 3,
  reviewedOn: '2026-09-12',
  reviewBy: '2026-12-12',
  owner: 'UCR clinical lead',
  overdue: false,
};

const serviceHandlers = [
  http.get('/api/bff/services/:id/criteria', () => HttpResponse.json(CRITERIA_VIEW)),
  http.post('/api/bff/services/:id/phoned', () => HttpResponse.json({ recorded: true }, { status: 201 })),
  http.post('/api/bff/services/:id/declined', () => HttpResponse.json({ recorded: true }, { status: 201 })),
];

const optionsHandlers = [
  http.get('/api/bff/cases/:ref/options', ({ params }) => {
    seenOptionsReads.push(String(params.ref));
    return HttpResponse.json(OPTIONS_VIEW);
  }),
];

export const advisorHandlers = [
  ...caseHandlers,
  ...pathwaysHandlers,
  ...optionsHandlers,
  ...serviceHandlers,
  http.get('/api/bff/board', () => HttpResponse.json(BOARD_A)),
  http.get('/api/bff/session', () =>
    HttpResponse.json({ role: 'advisor', services: [], sub: 'advisor-1', csrfToken: CSRF_TOKEN }),
  ),
  http.post('/api/bff/cases', ({ request }) => {
    seenCaseCreates.push(request.clone());
    return HttpResponse.json({ id: CASE_ID }, { status: 201 });
  }),
];
