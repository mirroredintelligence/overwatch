import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import {
  BOOKING_ID,
  SERVICE_WITH_OPEN_REQUEST,
  STATE_CONFIRMED,
  STATE_REQUESTED,
  TASK_CONFIRMED,
  TASK_REQUESTED,
} from '@/test/fixtures/bookings';

// The advisor's booking routes as the browser sees them (BFF, W20), and the back end's Task routes
// behind them (R09). The BFF answers the booking state, never the raw Task.

/** Every POST the browser sent to the booking BFF, newest last. */
export const seenBookingPosts: { body: unknown; csrf: string | null; idempotencyKey: string | null }[] = [];
/** Every GET the browser sent for one booking, newest last. */
export const seenBookingReads: string[] = [];
/** The booking's state as the back end holds it for the next read. Tests set it. */
export const bookingStore: { current: typeof STATE_REQUESTED | typeof STATE_CONFIRMED } = { current: STATE_REQUESTED };

export function resetBookingRequests() {
  seenBookingPosts.length = 0;
  seenBookingReads.length = 0;
  bookingStore.current = STATE_REQUESTED;
}

async function jsonBody(request: Request): Promise<unknown> {
  return (await request.json().catch(() => null)) as unknown;
}

export const bookingHandlers = [
  http.post('/api/bff/bookings', (async ({ request }) => {
    const body = await jsonBody(request);
    seenBookingPosts.push({
      body,
      csrf: request.headers.get('x-csrf-token'),
      idempotencyKey: request.headers.get('idempotency-key'),
    });
    const serviceId = (body as { serviceId?: unknown } | null)?.serviceId;
    if (serviceId === SERVICE_WITH_OPEN_REQUEST) {
      return HttpResponse.json({ code: 'open-request' }, { status: 409 });
    }
    return HttpResponse.json(STATE_REQUESTED, { status: 201, headers: { 'Cache-Control': 'no-store' } });
  }) as HttpResponseResolver),
  http.get('/api/bff/bookings/:id', (({ params }) => {
    seenBookingReads.push(String(params.id));
    return HttpResponse.json(bookingStore.current, { headers: { 'Cache-Control': 'no-store' } });
  }) as HttpResponseResolver),
];

/** The back end's Task routes, for the BFF's route tests. */
export const BACKEND_TASK_HANDLERS = (root: string) => [
  http.post(`${root}/Task`, (async ({ request }) => {
    const body = await jsonBody(request);
    const serviceId = (body as { owner?: { reference?: string } } | null)?.owner?.reference;
    if (serviceId === `HealthcareService/${SERVICE_WITH_OPEN_REQUEST}`) {
      return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 409 });
    }
    return HttpResponse.json(TASK_REQUESTED, { status: 201, headers: { Location: `/fhir/Task/${BOOKING_ID}` } });
  }) as HttpResponseResolver),
  http.get(`${root}/Task/:id`, (({ params }) => {
    if (params.id === 'missing') return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 404 });
    return HttpResponse.json(TASK_CONFIRMED);
  }) as HttpResponseResolver),
];

