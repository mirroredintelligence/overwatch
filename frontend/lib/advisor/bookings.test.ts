import { describe, expect, it } from 'vitest';
import { STATE_CONFIRMED, STATE_DECLINED, STATE_REQUESTED, TASK_CONFIRMED, TASK_DECLINED, TASK_EXPIRED, TASK_REQUESTED, CASE_REF, SERVICE_ID } from '@/test/fixtures/bookings';
import { bookingFromTask, bookingRequestTask, BookingShapeError, declineReasonWording, parseBookingState, PHONE_PROMPT_AFTER_MS } from './bookings';

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
