import type { Session } from '@/lib/auth/session';
import { fhirFetch } from '@/lib/fhir/client';
import { bookingFromTask, bookingRequestTask, type BookingState } from './bookings';

// Server-only. The advisor's booking calls to the back end's Task routes (R09). The session's back-end
// token is the only thing that says whose booking this is: no tenant or organisation is sent (DEC-130).

/** Opens a booking request for one case and one service. A 409 from the back end is thrown as a FhirError. */
export async function openBooking(
  session: Pick<Session, 'backendToken'>,
  caseRef: string,
  serviceId: string,
  idempotencyKey: string,
): Promise<BookingState> {
  const { data } = await fhirFetch<unknown>('/Task', {
    method: 'POST',
    body: bookingRequestTask(caseRef, serviceId),
    token: session.backendToken,
    idempotencyKey,
  });
  return bookingFromTask(data);
}

/** Reads one booking for the card. */
export async function readBooking(session: Pick<Session, 'backendToken'>, id: string): Promise<BookingState> {
  const { data } = await fhirFetch<unknown>(`/Task/${encodeURIComponent(id)}`, { token: session.backendToken });
  return bookingFromTask(data);
}

/**
 * Cancels a booking the advisor no longer needs (U20). The back end answers the Task; this returns the
 * status it now has. A 409 from the back end is thrown as a FhirError (the booking moved on).
 */
export async function cancelBooking(
  session: Pick<Session, 'backendToken'>,
  id: string,
  reason: string,
  idempotencyKey: string,
): Promise<BookingState> {
  const { data } = await fhirFetch<unknown>(`/Task/${encodeURIComponent(id)}/$cancel`, {
    method: 'POST',
    body: { resourceType: 'Parameters', parameter: [{ name: 'reason', valueCode: reason }] },
    token: session.backendToken,
    idempotencyKey,
  });
  return bookingFromTask(data);
}

/** The advisor has seen a withdrawal or a not-reached report: the back end stops the escalation (R17). */
export async function acknowledgeBooking(session: Pick<Session, 'backendToken'>, id: string, idempotencyKey: string): Promise<void> {
  await fhirFetch<unknown>(`/Task/${encodeURIComponent(id)}/$acknowledge`, {
    method: 'POST',
    token: session.backendToken,
    idempotencyKey,
  });
}
