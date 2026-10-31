import { ALERT_SEARCH, BOOKING_ACKNOWLEDGED, BOOKING_SEARCH, BOOKINGS } from '@/test/fixtures/backend-shapes';
import { describe, expect, it } from 'vitest';
import { STATE_CONFIRMED, STATE_DECLINED, STATE_REQUESTED, TASK_CONFIRMED, TASK_DECLINED, TASK_EXPIRED, TASK_REQUESTED, CASE_REF, SERVICE_ID } from '@/test/fixtures/bookings';
import {
  bookingFromTask,
  bookingRequestTask,
  bookingsFromSearch,
  BookingShapeError,
  declineReasonWording,
  deliveryWording,
  minutesBetween,
  parseBookingList,
  parseBookingState,
  PHONE_PROMPT_AFTER_MS,
  withdrawReasonWording,
  CANCEL_REASONS,
} from './bookings';
import {
  STATE_REQUESTED_OLD,
  STATE_REQUESTED_TENANT_POLICY,
  STATE_WITHDRAWN_ACKNOWLEDGED,
  TASK_REQUESTED_OLD,
  TASK_REQUESTED_TENANT_POLICY,
  TASK_WITHDRAWN_ACKNOWLEDGED,
} from '@/test/fixtures/bookings';
import { STATE_WITHDRAWN, STATE_NOT_REACHED, TASK_WITHDRAWN, TASK_NOT_REACHED } from '@/test/fixtures/bookings';

describe('bookingFromTask', () => {
  it('maps a requested Task to the advisor state, with the phone prompt five minutes after the request', () => {
    expect(bookingFromTask(TASK_REQUESTED)).toEqual(STATE_REQUESTED);
    expect(PHONE_PROMPT_AFTER_MS).toBe(5 * 60_000);
  });

  it('maps a confirmed Task with its confirmation time and no decline', () => {
    expect(bookingFromTask(TASK_CONFIRMED)).toEqual(STATE_CONFIRMED);
  });

  it('maps a declined Task with its time and its reason', () => {
    expect(bookingFromTask(TASK_DECLINED)).toEqual(STATE_DECLINED);
  });

  it('maps an expired Task with the time it expired at the reply-by time', () => {
    expect(bookingFromTask(TASK_EXPIRED)).toMatchObject({ status: 'expired', expiredAt: '2026-10-30T14:26:00Z' });
  });

  it.each([
    ['not a Task', { resourceType: 'Patient' }],
    ['no reference', { ...TASK_REQUESTED, identifier: [] }],
    ['no business status', { ...TASK_REQUESTED, businessStatus: undefined }],
    ['a status it does not know', { ...TASK_REQUESTED, businessStatus: { coding: [{ code: 'invented' }] } }],
  ])('refuses %s without naming the value', (_name, task) => {
    expect(() => bookingFromTask(task)).toThrow(BookingShapeError);
  });
});

describe('bookingRequestTask', () => {
  it('builds the booking-request Task the back end takes: its code, its case and its service only', () => {
    expect(bookingRequestTask(CASE_REF, SERVICE_ID)).toEqual({
      resourceType: 'Task',
      code: { coding: [{ code: 'booking-request' }] },
      focus: { reference: `ServiceRequest/${CASE_REF}` },
      owner: { reference: `HealthcareService/${SERVICE_ID}` },
    });
  });
});

describe('declineReasonWording', () => {
  it.each([
    ['full', 'full'],
    ['outside-criteria', 'outside criteria'],
    ['staffing-or-transport', 'staffing or transport'],
    ['other', 'other'],
    [null, 'not given'],
  ])('reads %s as %s', (code, words) => {
    expect(declineReasonWording(code)).toBe(words);
  });
});

describe('parseBookingState', () => {
  it('accepts the state the BFF answers and drops anything else', () => {
    expect(parseBookingState({ ...STATE_CONFIRMED, patient: 'Sample Patient' })).toEqual(STATE_CONFIRMED);
  });

  it('refuses an answer with no id', () => {
    expect(() => parseBookingState({ ...STATE_CONFIRMED, id: undefined })).toThrow(BookingShapeError);
  });
});

describe('bookingFromTask for a withdrawal and a not-reached report', () => {
  it('maps a withdrawn Task with its time and reason', () => {
    expect(bookingFromTask(TASK_WITHDRAWN)).toEqual(STATE_WITHDRAWN);
  });

  it('maps a not-reached Task with its time and reason', () => {
    expect(bookingFromTask(TASK_NOT_REACHED)).toEqual(STATE_NOT_REACHED);
  });
});

describe('withdrawReasonWording', () => {
  it.each([
    ['now-full', 'now full'],
    ['staffing', 'staffing'],
    ['cannot-reach-patient', 'cannot reach the patient'],
    ['other', 'other'],
    ['no-answer', 'No answer at the door'],
    ['not-at-address', 'Not at the address'],
    ['gone-to-hospital', 'Gone to hospital'],
  ])('reads %s as %s', (code, words) => {
    expect(withdrawReasonWording(code)).toBe(words);
  });

  it('offers the four cancel reasons in the order of the artboard', () => {
    expect(CANCEL_REASONS.map((reason) => reason.code)).toEqual(['caller-declined', 'no-longer-needed', 'other-route-found', 'entered-in-error']);
  });
});


describe('bookingFromTask against the Task the back end writes (R09, booking_task.py)', () => {
  it('reads a request: the reference, the times and the phone prompt five minutes after it', () => {
    expect(bookingFromTask(BOOKINGS.requested)).toEqual({
      id: 'bk-1',
      caseRef: 'case-1',
      serviceId: 'svc-1',
      delivery: 'delivered',
      acknowledgedAt: null,
      reference: '4821',
      status: 'requested',
      requestedAt: '2026-10-30T14:00:00Z',
      replyBy: '2026-10-30T14:10:00Z',
      phonePromptAt: '2026-10-30T14:05:00Z',
      confirmedAt: null,
      declinedAt: null,
      declineReason: null,
      expiredAt: null,
      withdrawnAt: null,
      withdrawReason: null,
    });
  });

  it('reads the confirmation time from the confirmed-at output', () => {
    expect(bookingFromTask(BOOKINGS.confirmed)).toMatchObject({ status: 'confirmed', confirmedAt: '2026-10-30T14:03:00Z' });
  });

  it('reads a decline with its reason and the time it was answered', () => {
    expect(bookingFromTask(BOOKINGS.declined)).toMatchObject({ status: 'declined', declineReason: 'full', declinedAt: '2026-10-30T14:03:00Z' });
  });

  it('reads an expiry with the time the back end ended it', () => {
    expect(bookingFromTask(BOOKINGS.expired)).toMatchObject({ status: 'expired', expiredAt: '2026-10-30T14:03:00Z' });
  });

  it('reads both cancelled states as cancelled', () => {
    expect(bookingFromTask(BOOKINGS.cancelledBefore).status).toBe('cancelled-before');
    expect(bookingFromTask(BOOKINGS.cancelledAfter).status).toBe('cancelled-after');
  });

  it('reads a withdrawal and a not-reached report with their reasons and the time they were made', () => {
    expect(bookingFromTask(BOOKINGS.withdrawn)).toMatchObject({
      status: 'withdrawn',
      withdrawReason: 'now-full',
      withdrawnAt: '2026-10-30T14:04:00Z',
      confirmedAt: '2026-10-30T14:03:00Z',
    });
    expect(bookingFromTask(BOOKINGS.notReached)).toMatchObject({ status: 'not-reached', withdrawReason: 'no-answer' });
  });

  it('puts every status the back end can write on the card (BOOKING_STATUSES lists them all)', () => {
    for (const task of Object.values(BOOKINGS)) expect(() => bookingFromTask(task)).not.toThrow();
  });
});


describe('what the back end now keeps on a booking (WB4: H-493, H-494, KI-451)', () => {
  it('reads the phone prompt time the tenant\'s policy gave, not five minutes after the request', () => {
    expect(bookingFromTask(TASK_REQUESTED_TENANT_POLICY)).toEqual(STATE_REQUESTED_TENANT_POLICY);
    expect(bookingFromTask(TASK_REQUESTED_TENANT_POLICY).phonePromptAt).toBe('2026-10-30T14:19:00Z');
  });

  it('falls back to five minutes for a booking from before the prompt time was kept', () => {
    expect(bookingFromTask(TASK_REQUESTED_OLD)).toEqual(STATE_REQUESTED_OLD);
  });

  it('reads the case and the service the booking is for', () => {
    expect(bookingFromTask(BOOKINGS.requested)).toMatchObject({ caseRef: 'case-1', serviceId: 'svc-1' });
  });

  it.each(['queued', 'sent', 'delivered', 'failed'])('reads the request message state %s', (state) => {
    const task = { ...TASK_REQUESTED_OLD, output: [{ type: { coding: [{ code: 'request-delivery' }] }, valueString: state }] };
    expect(bookingFromTask(task).delivery).toBe(state);
  });

  it('reads a state it does not know as unknown, never as delivered', () => {
    const task = { ...TASK_REQUESTED_OLD, output: [{ type: { coding: [{ code: 'request-delivery' }] }, valueString: 'whatever' }] };
    expect(bookingFromTask(task).delivery).toBeNull();
  });

  it('reads when a withdrawal was acknowledged, from the real back-end answer', () => {
    expect(bookingFromTask(BOOKING_ACKNOWLEDGED)).toMatchObject({ status: 'withdrawn', acknowledgedAt: '2026-10-30T14:09:00Z' });
    expect(bookingFromTask(TASK_WITHDRAWN_ACKNOWLEDGED)).toEqual(STATE_WITHDRAWN_ACKNOWLEDGED);
  });

  it('never carries who acknowledged it', () => {
    expect(JSON.stringify(bookingFromTask(BOOKING_ACKNOWLEDGED))).not.toContain('adv-2');
  });

  it('measures minutes between two instants, for the words on the card', () => {
    expect(minutesBetween('2026-10-30T14:16:00Z', '2026-10-30T14:19:00Z')).toBe(3);
    expect(minutesBetween('2026-10-30T14:16:00Z', '2026-10-30T14:24:30Z')).toBe(9);
  });
});

describe('deliveryWording (H-494): a text that was sent is not said to have arrived', () => {
  it.each([
    ['queued', 'Text waiting to be sent'],
    ['sent', 'Text sent'],
    ['delivered', 'Text delivered'],
    ['failed', 'Text not delivered'],
    [null, 'Text sent'],
  ] as const)('says %s as %s', (state, words) => {
    expect(deliveryWording(state)).toBe(words);
  });
});

describe('the search of a case\'s bookings and the open alerts', () => {
  it('reads the back end\'s search Bundle into booking states', () => {
    const found = bookingsFromSearch(BOOKING_SEARCH);
    expect(found.map((b) => b.status)).toEqual(expect.arrayContaining(['declined', 'requested']));
    expect(found).toHaveLength(2);
    expect(found.map((b) => b.delivery)).toEqual(expect.arrayContaining(['sent', 'queued']));
  });

  it('reads the open alerts: withdrawn bookings not yet answered', () => {
    const found = bookingsFromSearch(ALERT_SEARCH);
    expect(found).toHaveLength(1);
    expect(found[0]).toMatchObject({ status: 'withdrawn', acknowledgedAt: null, caseRef: 'case-1' });
  });

  it('reads an empty search as no bookings', () => {
    expect(bookingsFromSearch({ resourceType: 'Bundle', type: 'searchset', total: 0 })).toEqual([]);
  });

  it.each([
    ['not a Bundle', { resourceType: 'Patient' }],
    ['an entry that is not a Task', { resourceType: 'Bundle', entry: [{ resource: { resourceType: 'Patient' } }] }],
  ])('refuses %s', (_name, body) => {
    expect(() => bookingsFromSearch(body)).toThrow(BookingShapeError);
  });

  it('parses the BFF\'s list and drops anything beyond the booking fields', () => {
    const list = parseBookingList({ bookings: [{ ...STATE_REQUESTED_OLD, patient: 'Sample Patient' }] });
    expect(list).toEqual([STATE_REQUESTED_OLD]);
  });

  it('refuses a list that is not a list of bookings', () => {
    expect(() => parseBookingList({ bookings: 'x' })).toThrow(BookingShapeError);
    expect(() => parseBookingList(null)).toThrow(BookingShapeError);
  });
});
