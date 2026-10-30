import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { recordInto, type SeenRequest } from '../record';
import { CRITERIA_OVERVIEW, HISTORY, PENDING_CHANGE } from '@/test/fixtures/criteria';

// The owner's criteria BFF routes, as the browser sees them (W30, W31). Requests are kept per test.

export const seenCriteriaRequests: SeenRequest[] = [];

export function resetCriteriaRequests() {
  seenCriteriaRequests.length = 0;
}

const json = (body: unknown, status = 200) =>
  HttpResponse.json(body as Record<string, unknown>, { status, headers: { 'Cache-Control': 'no-store' } });

export const criteriaHandlers = [
  http.get('/api/bff/criteria/:serviceId', (async ({ request }) => {
    await recordInto(seenCriteriaRequests, request);
    return json(CRITERIA_OVERVIEW);
  }) as HttpResponseResolver),

  http.post('/api/bff/criteria/:serviceId/confirm', (async ({ request }) => {
    await recordInto(seenCriteriaRequests, request);
    return json({ reviewBy: '2027-04-30' });
  }) as HttpResponseResolver),

  http.post('/api/bff/criteria/:serviceId/submit', (async ({ request }) => {
    await recordInto(seenCriteriaRequests, request);
    return json({ version: 4, status: 'waiting' }, 201);
  }) as HttpResponseResolver),

  // W31: the approver's read, the approver's decision and the history.
  http.get('/api/bff/criteria/:serviceId/pending', (async ({ request }) => {
    await recordInto(seenCriteriaRequests, request);
    return json(PENDING_CHANGE);
  }) as HttpResponseResolver),

  http.post('/api/bff/criteria/:serviceId/pending/decision', (async ({ request }) => {
    await recordInto(seenCriteriaRequests, request);
    return json({ status: 'current', version: 4 });
  }) as HttpResponseResolver),

  http.get('/api/bff/criteria/:serviceId/history', (async ({ request }) => {
    await recordInto(seenCriteriaRequests, request);
    return json(HISTORY);
  }) as HttpResponseResolver),
];
