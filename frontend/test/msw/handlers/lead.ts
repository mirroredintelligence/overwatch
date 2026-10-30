import { http, HttpResponse } from 'msw';
import { OVERVIEW_SHIFT_LEAD } from '@/test/fixtures/lead';

// The shift lead's BFF routes, for component tests (W17). The default answers are the "ShiftLead"
// sample. A test that needs another answer uses server.use(...) in the test itself.

export type SeenLeadPost = { path: string; csrf: string | null; idempotencyKey: string | null };

/** Every lead POST this test file's handlers saw, newest last. */
export const seenLeadPosts: SeenLeadPost[] = [];

export function resetLeadPosts() {
  seenLeadPosts.length = 0;
}

export const leadHandlers = [
  http.get('/api/bff/lead/overview', () =>
    HttpResponse.json(OVERVIEW_SHIFT_LEAD, { headers: { 'Cache-Control': 'no-store' } }),
  ),
  http.post('/api/bff/lead/services/:id/remind', ({ request, params }) => {
    seenLeadPosts.push({
      path: `/api/bff/lead/services/${String(params.id)}/remind`,
      csrf: request.headers.get('x-csrf-token'),
      idempotencyKey: request.headers.get('idempotency-key'),
    });
    return HttpResponse.json({ state: 'sent' }, { status: 202, headers: { 'Cache-Control': 'no-store' } });
  }),
];
