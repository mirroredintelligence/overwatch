import { http, HttpResponse } from 'msw';
import { BOARD_A } from '@/test/fixtures/board';

// Browser-facing stubs for the advisor screens (W10 to W16, W50): the BFF routes a client component
// calls, answered from fixtures. Every request a test makes must match a handler (test/setup.ts).

export const CSRF_TOKEN = 'csrf-token-for-tests-only-0000000000000000000';
export const CASE_ID = '4821';

/** Every POST /api/bff/cases this file's handlers saw, newest last. */
export const seenCaseCreates: Request[] = [];

export function resetSeenAdvisorRequests() {
  seenCaseCreates.length = 0;
}

export const advisorHandlers = [
  http.get('/api/bff/board', () => HttpResponse.json(BOARD_A)),
  http.get('/api/bff/session', () =>
    HttpResponse.json({ role: 'advisor', services: [], sub: 'advisor-1', csrfToken: CSRF_TOKEN }),
  ),
  http.post('/api/bff/cases', ({ request }) => {
    seenCaseCreates.push(request.clone());
    return HttpResponse.json({ id: CASE_ID }, { status: 201 });
  }),
];
