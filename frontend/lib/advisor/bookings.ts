import { londonTime } from '@/lib/board/format';

// The advisor's view of a booking (W20, R09). Pure: no I/O. The BFF maps the back end's FHIR Task
// to this state, and the browser parses the BFF's answer with the same rules, so the card never
// reads a Task directly.

/**
 * [ASSUMED] domain-rules 3: the phone prompt comes five minutes after the request. Used only for a booking
 * the back end did not give a prompt time (one made before it kept the tenant's own, H-493).
 */
export const PHONE_PROMPT_AFTER_MINUTES = 5;
export const PHONE_PROMPT_AFTER_MS = PHONE_PROMPT_AFTER_MINUTES * 60_000;

export const BOOKING_STATUSES = [
  'requested',
  'confirmed',
  'declined',
  'expired',
  'cancelled-before',
  'cancelled-after',
  'withdrawn',
  'not-reached',
  'completed',
] as const;
export type BookingStatus = (typeof BOOKING_STATUSES)[number];

/** The state of the message that asked the service (the back end's delivery status of the request). */
export const DELIVERY_STATES = ['queued', 'sent', 'delivered', 'failed'] as const;
export type DeliveryState = (typeof DELIVERY_STATES)[number];

export type BookingState = {
  id: string;
  /** The case the booking is for, and the service it asks (a case's bookings are matched to its services by these). */
  caseRef: string;
  serviceId: string;
  reference: string;
  status: BookingStatus;
  requestedAt: string;
  replyBy: string;
  phonePromptAt: string;
  confirmedAt: string | null;
  declinedAt: string | null;
  declineReason: string | null;
  expiredAt: string | null;
  /** When the service withdrew or reported the patient not reached (the back end's ended time). */
  withdrawnAt: string | null;
  /** The withdrawal or not-reached reason, as the service gave it. */
  withdrawReason: string | null;
  /** The state of the request message, or null when the back end did not say (WB4, H-494). */
  delivery: DeliveryState | null;
  /** When an advisor answered a withdrawal or a not-reached report, or null while it is open (KI-451). Never who. */
  acknowledgedAt: string | null;
};

/** The reasons an advisor may give for cancelling (U20, the artboard order). */
export const CANCEL_REASONS = [
  { code: 'caller-declined', label: 'Caller declined', dataEl: 'ADV-CANCEL-REASON-DECLINED' },
  { code: 'no-longer-needed', label: 'No longer needed', dataEl: 'ADV-CANCEL-REASON-NEEDLESS' },
  { code: 'other-route-found', label: 'Other route found', dataEl: 'ADV-CANCEL-REASON-ROUTE' },
  { code: 'entered-in-error', label: 'Entered in error', dataEl: 'ADV-CANCEL-REASON-ERROR' },
] as const;
export type CancelReason = (typeof CANCEL_REASONS)[number]['code'];

/** A value the card cannot read. The message never names the value. */
export class BookingShapeError extends Error {
  constructor() {
    super('The booking did not have the expected shape.');
    this.name = 'BookingShapeError';
  }
}

type Json = Record<string, unknown>;

function record(value: unknown): Json {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new BookingShapeError();
  return value as Json;
}

function text(value: unknown, max = 200): string {
  if (typeof value !== 'string' || value.length === 0 || value.length > max) throw new BookingShapeError();
  return value;
}

function instant(value: unknown): string {
  const parsed = text(value, 40);
  if (Number.isNaN(Date.parse(parsed))) throw new BookingShapeError();
  return parsed;
}

function instantOrNull(value: unknown): string | null {
  return value === null || value === undefined ? null : instant(value);
}

/** Whole minutes from one instant to another, rounded down. */
export function minutesBetween(from: string, to: string): number {
  return Math.floor((Date.parse(to) - Date.parse(from)) / 60_000);
}

function addMinutes(value: string, minutes: number): string {
  return new Date(Date.parse(value) + minutes * 60_000).toISOString().replace('.000Z', 'Z');
}

/** The value of the first output entry of this type, or undefined. */
function outputOf(task: Json, type: string): unknown {
  const outputs = Array.isArray(task.output) ? task.output : [];
  for (const entry of outputs) {
    const coding = (record(record(entry).type).coding ?? []) as unknown[];
    const first = coding[0];
    if (typeof first === 'object' && first !== null && (first as Json).code === type) {
      const { valueDateTime, valueString } = entry as Json;
      return valueDateTime ?? valueString;
    }
  }
  return undefined;
}

/** The id after the slash of a FHIR reference (`ServiceRequest/case-1001` is `case-1001`). */
function idOfReference(value: unknown): string {
  const reference = record(value).reference;
  const slash = typeof reference === 'string' ? reference.indexOf('/') : -1;
  if (typeof reference !== 'string' || slash < 0) throw new BookingShapeError();
  return text(reference.slice(slash + 1), 64);
}

function deliveryOf(value: unknown): DeliveryState | null {
  return DELIVERY_STATES.find((known) => known === value) ?? null;
}

/** The advisor's state of a booking, from the back end's Task (R09). A Task that does not read is refused. */
export function bookingFromTask(value: unknown): BookingState {
  const task = record(value);
  if (task.resourceType !== 'Task') throw new BookingShapeError();
  const identifiers = Array.isArray(task.identifier) ? task.identifier : [];
  const reference = identifiers.map((item) => record(item).value).find((v) => typeof v === 'string');
  const codings: unknown = record(task.businessStatus).coding;
  const firstCode = Array.isArray(codings) ? record(codings[0]).code : undefined;
  const status = BOOKING_STATUSES.find((known) => known === firstCode);
  if (status === undefined) throw new BookingShapeError();
  const requestedAt = instant(task.authoredOn);
  const replyBy = instant(record(record(task.restriction).period).end);
  const period = record(task.executionPeriod ?? {});
  const ended = instantOrNull(period.end);
  const declined = status === 'declined';
  const ending = status === 'withdrawn' || status === 'not-reached';
  const confirmed = outputOf(task, 'confirmed-at');
  const reason = outputOf(task, 'reason');
  // The tenant's own prompt time, kept on the booking by the back end (H-493); five minutes only for one that has none.
  const promptAt = outputOf(task, 'phone-prompt-at');
  const acknowledged = outputOf(task, 'acknowledged-at');
  return {
    id: text(task.id, 64),
    caseRef: idOfReference(task.focus),
    serviceId: idOfReference(task.owner),
    reference: text(reference, 80),
    status,
    requestedAt,
    replyBy,
    phonePromptAt: promptAt === undefined ? addMinutes(requestedAt, PHONE_PROMPT_AFTER_MINUTES) : instant(promptAt),
    confirmedAt: confirmed === undefined ? null : instant(confirmed),
    declinedAt: declined ? ended : null,
    declineReason: declined ? ((outputOf(task, 'reason') as string | undefined) ?? null) : null,
    expiredAt: status === 'expired' ? (ended ?? replyBy) : null,
    withdrawnAt: ending ? ended : null,
    withdrawReason: ending ? ((reason as string | undefined) ?? null) : null,
    delivery: deliveryOf(outputOf(task, 'request-delivery')),
    acknowledgedAt: acknowledged === undefined ? null : instant(acknowledged),
  };
}

/** The bookings a search of the back end's Tasks found (a Bundle): a case's bookings, or the open alerts. */
export function bookingsFromSearch(value: unknown): BookingState[] {
  const bundle = record(value);
  if (bundle.resourceType !== 'Bundle') throw new BookingShapeError();
  const entries = bundle.entry === undefined ? [] : bundle.entry;
  if (!Array.isArray(entries)) throw new BookingShapeError();
  return entries.map((entry) => bookingFromTask(record(entry).resource));
}

/** The words for the state of the request message. A state not known reads as the plain "sent": never as delivered. */
export function deliveryWording(state: DeliveryState | null): string {
  switch (state) {
    case 'queued':
      return 'Text waiting to be sent';
    case 'delivered':
      return 'Text delivered';
    case 'failed':
      return 'Text not delivered';
    default:
      return 'Text sent';
  }
}

/** The Task the browser asks the back end to open: the booking request for one case and one service. */
export function bookingRequestTask(caseRef: string, serviceId: string) {
  return {
    resourceType: 'Task',
    code: { coding: [{ code: 'booking-request' }] },
    focus: { reference: `ServiceRequest/${caseRef}` },
    owner: { reference: `HealthcareService/${serviceId}` },
  };
}

const WITHDRAW_WORDS: Readonly<Record<string, string>> = {
  'now-full': 'now full',
  staffing: 'staffing',
  'cannot-reach-patient': 'cannot reach the patient',
  other: 'other',
  'not-at-address': 'Not at the address',
  'no-answer': 'No answer at the door',
  'gone-to-hospital': 'Gone to hospital',
};

/** The words a withdrawal or not-reached reason reads as on the alert. */
export function withdrawReasonWording(code: string): string {
  return WITHDRAW_WORDS[code] ?? code.replace(/-/g, ' ');
}

const DECLINE_WORDS: Readonly<Record<string, string>> = {
  full: 'full',
  'outside-criteria': 'outside criteria',
  'staffing-or-transport': 'staffing or transport',
  other: 'other',
};

/** The words a decline reason reads as on the card. No reason given reads as "not given". */
export function declineReasonWording(code: string | null): string {
  if (code === null) return 'not given';
  return DECLINE_WORDS[code] ?? code.replace(/-/g, ' ');
}

/** The booking state the BFF answers. Anything beyond these fields is dropped. */
export function parseBookingState(value: unknown): BookingState {
  const body = record(value);
  const status = BOOKING_STATUSES.find((known) => known === body.status);
  if (status === undefined) throw new BookingShapeError();
  return {
    id: text(body.id, 64),
    caseRef: text(body.caseRef, 64),
    serviceId: text(body.serviceId, 64),
    reference: text(body.reference, 80),
    status,
    requestedAt: instant(body.requestedAt),
    replyBy: instant(body.replyBy),
    phonePromptAt: instant(body.phonePromptAt),
    confirmedAt: instantOrNull(body.confirmedAt),
    declinedAt: instantOrNull(body.declinedAt),
    declineReason: body.declineReason === null || body.declineReason === undefined ? null : text(body.declineReason, 80),
    expiredAt: instantOrNull(body.expiredAt),
    withdrawnAt: instantOrNull(body.withdrawnAt),
    withdrawReason: body.withdrawReason === null || body.withdrawReason === undefined ? null : text(body.withdrawReason, 80),
    delivery: deliveryOf(body.delivery),
    acknowledgedAt: instantOrNull(body.acknowledgedAt),
  };
}

/** The list the BFF answers for a case's bookings or the open alerts. Anything beyond the booking fields is dropped. */
export function parseBookingList(value: unknown): BookingState[] {
  const list = record(value).bookings;
  if (!Array.isArray(list)) throw new BookingShapeError();
  return list.map((item) => parseBookingState(item));
}

/** An instant as London time, HH:MM. */
export function clock(instantText: string): string {
  return londonTime(instantText);
}
