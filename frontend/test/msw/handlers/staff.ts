import { http, HttpResponse } from 'msw';

// The browser's own session read. Every client component that posts reads the CSRF token here
// once, so every test has it. The role is a lead's, the sample sign-in.
export const SAMPLE_CSRF = 'csrf-sample-staff';

export const staffHandlers = [
  http.get('/api/bff/session', () =>
    HttpResponse.json(
      { role: 'lead', services: [], sub: 'sample-sub', csrfToken: SAMPLE_CSRF },
      { headers: { 'Cache-Control': 'no-store' } },
    ),
  ),
];
