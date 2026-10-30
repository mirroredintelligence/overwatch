import { describe, expect, it } from 'vitest';
import { BOOKING_CHANGE_VIEW, BOOKING_REQUEST_VIEW, csrfFor, LINK } from '@/test/fixtures/links';
import { LinkShapeError, parseBookingView, parseOpenLink } from './model';

const requestView = { ...BOOKING_REQUEST_VIEW, csrfToken: csrfFor(LINK.booking) };
const changeView = { ...BOOKING_CHANGE_VIEW, csrfToken: csrfFor(LINK.bookingChange) };

describe('parseBookingView', () => {
  it('reads a booking request as L02 answers it, with the reference, the rows and the coordination team phone', () => {
    expect(parseBookingView(requestView)).toEqual({
      state: 'ok',
      purpose: 'booking-request',
      csrfToken: csrfFor(LINK.booking),
      reference: '4821',
      serviceName: 'UCR West',
      ageBand: '80+',
      need: 'fall-no-injury and frailty',
      urgency: 'within 2 hrs',
      replyBy: '2026-10-23T13:26:00Z',
      bookingStatus: 'requested',
      coordinationPhone: '0300 123 4567',
    });
  });

  it('reads a change view, which has no reply-by time', () => {
    const view = parseBookingView(changeView);
    expect(view.purpose).toBe('booking-change');
    expect(view.bookingStatus).toBe('confirmed');
    expect(view.replyBy).toBeNull();
  });

  it('allows a missing coordination phone as null, and drops fields it does not read', () => {
    const view = parseBookingView({ ...requestView, coordinationPhone: null, postcode: 'DT4 8XX', name: 'Sample Patient' });
    expect(view.coordinationPhone).toBeNull();
    expect(JSON.stringify(view)).not.toContain('DT4');
    expect(JSON.stringify(view)).not.toContain('Sample Patient');
  });

  it.each([
    ['a wrong state', { ...requestView, state: 'closed' }],
    ['no reference', { ...requestView, reference: undefined }],
    ['a purpose that is not a booking', { ...requestView, purpose: 'capacity-reply' }],
    ['a booking status that is not a word', { ...requestView, bookingStatus: 3 }],
  ])('refuses %s', (_name, value) => {
    expect(() => parseBookingView(value)).toThrow(LinkShapeError);
  });
});

describe('parseOpenLink', () => {
  it('sends a booking purpose to the booking reader and a capacity purpose to the capacity reader', () => {
    expect(parseOpenLink(requestView).kind).toBe('booking');
    expect(parseOpenLink(changeView).kind).toBe('booking');
    expect(
      parseOpenLink({
        state: 'ok',
        purpose: 'capacity-reply',
        serviceName: 'UCR West',
        unitLabel: 'referrals in the next 2 hrs',
        recordedValue: null,
        asOf: null,
        usualMin: 0,
        usualMax: 8,
        replyBy: '2026-10-23T07:30:00Z',
        nextDue: null,
        csrfToken: 'csrf',
      }).kind,
    ).toBe('capacity');
  });
});

describe('the booking views the back end writes (L02, booking_links.py)', () => {
  it('reads the request view, with a reply-by time written with an offset', async () => {
    const { LINK_REQUEST_VIEW } = await import('@/test/fixtures/backend-shapes');
    expect(parseOpenLink(LINK_REQUEST_VIEW)).toEqual({
      kind: 'booking',
      view: {
        state: 'ok',
        purpose: 'booking-request',
        csrfToken: 'csrf-sample',
        reference: '4821',
        serviceName: 'UCR West',
        ageBand: '80+',
        need: 'fall-no-injury and frailty',
        urgency: 'within 2 hrs',
        replyBy: '2026-10-30T14:10:00+00:00',
        bookingStatus: 'requested',
        coordinationPhone: '0300 123 4567',
      },
    });
  });

  it('reads the change view, which has no reply-by time', async () => {
    const { LINK_CHANGE_VIEW } = await import('@/test/fixtures/backend-shapes');
    const link = parseOpenLink(LINK_CHANGE_VIEW);
    expect(link.kind).toBe('booking');
    if (link.kind === 'booking') {
      expect(link.view).toMatchObject({ purpose: 'booking-change', bookingStatus: 'confirmed', replyBy: null });
    }
  });
});
