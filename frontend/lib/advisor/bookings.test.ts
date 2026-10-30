import { BOOKINGS } from '@/test/fixtures/backend-shapes';
import { describe, expect, it } from 'vitest';
import { STATE_CONFIRMED, STATE_DECLINED, STATE_REQUESTED, TASK_CONFIRMED, TASK_DECLINED, TASK_EXPIRED, TASK_REQUESTED, CASE_REF, SERVICE_ID } from '@/test/fixtures/bookings';
import { bookingFromTask, bookingRequestTask, BookingShapeError, declineReasonWording, parseBookingState, PHONE_PROMPT_AFTER_MS, withdrawReasonWording, CANCEL_REASONS } from './bookings';
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
