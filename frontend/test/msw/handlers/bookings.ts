import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import {
  BOOKING_ID,
  CASE_REF,
  searchBundle,
  SERVICE_WITH_OPEN_REQUEST,
  STATE_CANCELLED,
  STATE_REQUESTED,
  TASK_CONFIRMED,
  TASK_REQUESTED,
  TASK_WITHDRAWN,
} from '@/test/fixtures/bookings';

// The advisor's booking routes as the browser sees them (BFF, W20), and the back end's Task routes
// behind them (R09). The BFF answers the booking state, never the raw Task.

/** Every POST the browser sent to the booking BFF, newest last. */
export const seenBookingPosts: { body: unknown; csrf: string | null; idempotencyKey: string | null }[] = [];
/** Every GET the browser sent for one booking, newest last. */
export const seenBookingReads: string[] = [];
/** The booking's state as the back end holds it for the next read. Tests set it. */
export const bookingStore: { current: { status: string } & Record<string, unknown>; refuseCancel: boolean } = {
  current: STATE_REQUESTED,
  refuseCancel: false,
};

/** The case's bookings as the BFF's list answers them (`GET /api/bff/bookings?case=`). Tests set it. */
export const caseBookings: { current: Record<string, unknown>[] } = { current: [] };
/** The open alerts as the BFF's list answers them (`GET /api/bff/bookings?alert=open`). Tests set it. */
export const openAlerts: { current: Record<string, unknown>[] } = { current: [] };
/** The case of every read of a case's bookings, newest last. */
export const seenBookingCaseReads: string[] = [];
/** The number of reads of the open alerts. */
export const seenAlertReads: { count: number } = { count: 0 };

export function resetBookingRequests() {
  caseBookings.current = [];
  openAlerts.current = [];
  seenBookingCaseReads.length = 0;
  seenAlertReads.count = 0;
  seenBookingPosts.length = 0;
  seenBookingReads.length = 0;
  seenBookingCancels.length = 0;
  seenAcknowledgements.length = 0;
  bookingStore.current = STATE_REQUESTED;
  bookingStore.refuseCancel = false;
}

async function jsonBody(request: Request): Promise<unknown> {
  return (await request.json().catch(() => null)) as unknown;
}

/** Every cancel the browser sent, newest last. */
export const seenBookingCancels: { id: string; body: unknown; csrf: string | null; idempotencyKey: string | null }[] = [];
/** Every acknowledgement the browser sent, newest last. */
export const seenAcknowledgements: { id: string; csrf: string | null; idempotencyKey: string | null }[] = [];

export const bookingHandlers = [
  http.post('/api/bff/bookings/:id/cancel', (async ({ request, params }) => {
    const body = await jsonBody(request);
    const id = String(params.id);
    seenBookingCancels.push({ id, body, csrf: request.headers.get('x-csrf-token'), idempotencyKey: request.headers.get('idempotency-key') });
    if (bookingStore.refuseCancel) {
      return HttpResponse.json({ code: 'state-changed', status: 'confirmed' }, { status: 409 });
    }
    bookingStore.current = STATE_CANCELLED;
    return HttpResponse.json({ status: 'cancelled-before' }, { status: 200 });
  }) as HttpResponseResolver),
  http.post('/api/bff/bookings/:id/acknowledge', (async ({ request, params }) => {
    seenAcknowledgements.push({
      id: String(params.id),
      csrf: request.headers.get('x-csrf-token'),
      idempotencyKey: request.headers.get('idempotency-key'),
    });
    return HttpResponse.json({ acknowledged: true }, { status: 200 });
  }) as HttpResponseResolver),
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
  http.get('/api/bff/bookings', (({ request }) => {
    const url = new URL(request.url);
    const caseRef = url.searchParams.get('case');
    if (caseRef !== null) {
      seenBookingCaseReads.push(caseRef);
      return HttpResponse.json({ bookings: caseBookings.current }, { headers: { 'Cache-Control': 'no-store' } });
    }
    if (url.searchParams.get('alert') === 'open') {
      seenAlertReads.count += 1;
      return HttpResponse.json({ bookings: openAlerts.current }, { headers: { 'Cache-Control': 'no-store' } });
    }
    return HttpResponse.json({ code: 'invalid' }, { status: 400 });
  }) as HttpResponseResolver),
  http.get('/api/bff/bookings/:id', (({ params }) => {
    seenBookingReads.push(String(params.id));
    return HttpResponse.json(bookingStore.current, { headers: { 'Cache-Control': 'no-store' } });
  }) as HttpResponseResolver),
];

/** The query of every search of Tasks the back end saw, newest last. */
export const seenTaskSearches: string[] = [];

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
  http.post(`${root}/Task/:id/$cancel`, (({ params }) => {
    if (params.id === 'missing') return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 404 });
    if (params.id === 'taken') return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 409 });
    return HttpResponse.json({ ...TASK_REQUESTED, businessStatus: { coding: [{ code: 'cancelled-before' }] } });
  }) as HttpResponseResolver),
  http.post(`${root}/Task/:id/$acknowledge`, (() =>
    HttpResponse.json({
      resourceType: 'Parameters',
      parameter: [{ name: 'acknowledged', valueBoolean: true }],
    })) as HttpResponseResolver),
  http.get(`${root}/Task`, (({ request }) => {
    const url = new URL(request.url);
    const focus = url.searchParams.get('focus');
    if (focus !== null) {
      seenTaskSearches.push(url.search);
      return HttpResponse.json(searchBundle(focus === `ServiceRequest/${CASE_REF}` ? [TASK_REQUESTED, TASK_CONFIRMED] : []));
    }
    if (url.searchParams.get('alert') === 'open') {
      seenTaskSearches.push(url.search);
      return HttpResponse.json(searchBundle([TASK_WITHDRAWN]));
    }
    return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 400 });
  }) as HttpResponseResolver),
  http.get(`${root}/Task/:id`, (({ params }) => {
    if (params.id === 'missing') return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [] }, { status: 404 });
    return HttpResponse.json(TASK_CONFIRMED);
  }) as HttpResponseResolver),
];

