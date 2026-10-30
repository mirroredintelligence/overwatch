import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { recordInto, type SeenRequest } from '../record';
import { CRITERIA_OVERVIEW } from '@/test/fixtures/criteria';

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
];
