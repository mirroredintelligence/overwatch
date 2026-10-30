// Sample booking Tasks for the advisor tests (R09, the back end's FHIR Task as booking_task.py
// writes it). Sample values only: booking 4821, UCR West, case-1001. No patient information.
// Times are 30 October 2026 in GMT (London), so 14:16 UTC is 14:16 on the wall.

export const SERVICE_ID = 'ucr-west';
export const CASE_REF = 'case-1001';
export const BOOKING_ID = 'bk-4821';
export const SERVICE_PHONE = '0300 123 4567';

const requestedAt = '2026-10-30T14:16:00Z';

/** A Task as the back end sends it. The fields the advisor card reads are the ones the mapping names. */
function task(id: string, businessStatus: string, extra: Record<string, unknown> = {}) {
  return {
    resourceType: 'Task',
    id,
    status: 'requested',
    businessStatus: { coding: [{ system: 'booking-status', code: businessStatus }] },
    intent: 'order',
    authoredOn: requestedAt,
    lastModified: requestedAt,
    identifier: [{ system: 'booking-reference', value: '4821' }],
    restriction: { period: { end: '2026-10-30T14:26:00Z' } },
    focus: { reference: `ServiceRequest/${CASE_REF}` },
    owner: { reference: `HealthcareService/${SERVICE_ID}` },
    requester: { reference: 'Practitioner/advisor-1' },
    executionPeriod: { start: requestedAt },
    ...extra,
  };
}

export const TASK_REQUESTED = task(BOOKING_ID, 'requested');

export const TASK_CONFIRMED = task(BOOKING_ID, 'confirmed', {
  executionPeriod: { start: requestedAt, end: '2026-10-30T14:19:00Z' },
  output: [
    { type: { coding: [{ code: 'decision' }] }, valueCodeableConcept: { coding: [{ code: 'confirmed' }] } },
    { type: { coding: [{ code: 'confirmed-at' }] }, valueDateTime: '2026-10-30T14:19:00Z' },
  ],
});

export const TASK_DECLINED = task(BOOKING_ID, 'declined', {
  executionPeriod: { start: requestedAt, end: '2026-10-30T14:19:00Z' },
  output: [
    { type: { coding: [{ code: 'decision' }] }, valueCodeableConcept: { coding: [{ code: 'declined' }] } },
    { type: { coding: [{ code: 'reason' }] }, valueString: 'outside-criteria' },
  ],
});

export const TASK_EXPIRED = task(BOOKING_ID, 'expired');

export const TASK_WITHDRAWN = task(BOOKING_ID, 'withdrawn', {
  executionPeriod: { start: requestedAt, end: '2026-10-30T14:41:00Z' },
  output: [
    { type: { coding: [{ code: 'decision' }] }, valueCodeableConcept: { coding: [{ code: 'confirmed' }] } },
    { type: { coding: [{ code: 'confirmed-at' }] }, valueDateTime: '2026-10-30T14:19:00Z' },
    { type: { coding: [{ code: 'reason' }] }, valueString: 'staffing' },
  ],
});

export const TASK_NOT_REACHED = task(BOOKING_ID, 'not-reached', {
  executionPeriod: { start: requestedAt, end: '2026-10-30T14:41:00Z' },
  output: [
    { type: { coding: [{ code: 'reason' }] }, valueString: 'no-answer' },
  ],
});

/** The advisor-side state of a booking, as the BFF answers it (lib/advisor/bookings.ts). */
export const STATE_REQUESTED = {
  id: BOOKING_ID,
  reference: '4821',
  status: 'requested',
  requestedAt,
  replyBy: '2026-10-30T14:26:00Z',
  phonePromptAt: '2026-10-30T14:21:00Z',
  confirmedAt: null,
  declinedAt: null,
  declineReason: null,
  expiredAt: null,
  withdrawnAt: null,
  withdrawReason: null,
} as const;

export const STATE_CONFIRMED = {
  ...STATE_REQUESTED,
  status: 'confirmed',
  confirmedAt: '2026-10-30T14:19:00Z',
} as const;

export const STATE_DECLINED = {
  ...STATE_REQUESTED,
  status: 'declined',
  declinedAt: '2026-10-30T14:19:00Z',
  declineReason: 'outside-criteria',
} as const;

export const STATE_DECLINED_NO_REASON = { ...STATE_DECLINED, declineReason: null } as const;

export const STATE_EXPIRED = { ...STATE_REQUESTED, status: 'expired', expiredAt: '2026-10-30T14:26:00Z' } as const;

/** A confirmed booking the service withdrew at 14:41 for staffing (W21). */
export const STATE_WITHDRAWN = {
  ...STATE_CONFIRMED,
  status: 'withdrawn',
  withdrawnAt: '2026-10-30T14:41:00Z',
  withdrawReason: 'staffing',
} as const;

/** A confirmed booking the service could not reach the patient for (W21). */
export const STATE_NOT_REACHED = {
  ...STATE_CONFIRMED,
  status: 'not-reached',
  withdrawnAt: '2026-10-30T14:41:00Z',
  withdrawReason: 'no-answer',
} as const;

/** A booking the advisor cancelled before the service answered (W21). */
export const STATE_CANCELLED = { ...STATE_REQUESTED, status: 'cancelled-before' } as const;

/** A service whose request is already waiting: the back end answers 409 for it. */
export const SERVICE_WITH_OPEN_REQUEST = 'ucr-busy';
