import { describe, expect, it } from 'vitest';
import {
  londonHm,
  LinkShapeError,
  parseClosed,
  parseLinkAnswered,
  parseLinkView,
  splitUnitLabel,
} from './model';

const VIEW = {
  state: 'ok',
  purpose: 'capacity-reply',
  serviceName: 'UCR West',
  unitLabel: 'referrals in the next 2 hrs',
  recordedValue: 3,
  asOf: '2026-10-23T07:15:00Z',
  usualMin: 0,
  usualMax: 8,
  replyBy: '2026-10-23T09:30:00Z',
  nextDue: '2026-10-23T11:00:00Z',
  csrfToken: 'csrf-sample',
};

describe('splitUnitLabel', () => {
  it('splits the window off at " in " so the question reads "How many referrals can you take in the next 2 hrs?"', () => {
    expect(splitUnitLabel('referrals in the next 2 hrs')).toEqual({
      noun: 'referrals',
      window: 'in the next 2 hrs',
    });
  });

  it('keeps a unit with no window whole', () => {
    expect(splitUnitLabel('beds')).toEqual({ noun: 'beds', window: '' });
  });
});

describe('londonHm', () => {
  it('shows the London local time, British summer time in October before the 25th', () => {
    expect(londonHm('2026-10-23T09:12:00Z')).toBe('10:12');
  });

  it('shows the London local time after the clocks go back', () => {
    expect(londonHm('2026-10-26T23:30:00Z')).toBe('23:30');
  });
});

describe('parseLinkView', () => {
  it('accepts the back end’s open answer and keeps the fields the page reads', () => {
    expect(parseLinkView(VIEW)).toEqual(VIEW);
  });

  it('drops any field it does not know, such as a tenant, so nothing unexpected reaches a component', () => {
    const parsed = parseLinkView({ ...VIEW, tenantId: 'tenant-a' });
    expect(parsed).not.toHaveProperty('tenantId');
  });

  it('accepts no recorded figure and no next due time', () => {
    expect(parseLinkView({ ...VIEW, recordedValue: null, asOf: null, nextDue: null })).toMatchObject({
      recordedValue: null,
      asOf: null,
      nextDue: null,
    });
  });

  it('refuses an answer that is not state ok, and one with a missing or wrong field', () => {
    expect(() => parseLinkView({ ...VIEW, state: 'expired' })).toThrow(LinkShapeError);
    expect(() => parseLinkView({ ...VIEW, csrfToken: undefined })).toThrow(LinkShapeError);
    expect(() => parseLinkView({ ...VIEW, usualMax: '8' })).toThrow(LinkShapeError);
    expect(() => parseLinkView(null)).toThrow(LinkShapeError);
  });
});

describe('parseLinkAnswered', () => {
  const ANSWER = {
    serviceName: 'UCR West',
    value: 3,
    unitLabel: 'referrals in the next 2 hrs',
    recordedAt: '2026-10-23T09:12:00Z',
    nextDue: '2026-10-23T11:00:00Z',
  };

  it('accepts the back end’s recorded answer', () => {
    expect(parseLinkAnswered(ANSWER)).toEqual(ANSWER);
  });

  it('refuses a figure that is not a whole number from 0 to 999', () => {
    expect(() => parseLinkAnswered({ ...ANSWER, value: 1000 })).toThrow(LinkShapeError);
    expect(() => parseLinkAnswered({ ...ANSWER, value: 2.5 })).toThrow(LinkShapeError);
  });
});

describe('parseClosed: what a closed link says (KI-169, KI-648, KI-649, KI-664, KI-665)', () => {
  it('reads a closed booking link: its kind, reference, times and the coordination number', () => {
    expect(
      parseClosed({
        state: 'cancelled',
        kind: 'booking',
        reference: '4821',
        closedAt: '2026-10-23T13:40:00Z',
        confirmedAt: '2026-10-23T13:19:00Z',
        cancelledAt: '2026-10-23T13:40:00Z',
        coordinationPhone: '0300 123 4567',
      }),
    ).toEqual({
      state: 'cancelled',
      kind: 'booking',
      reference: '4821',
      closedAt: '2026-10-23T13:40:00Z',
      confirmedAt: '2026-10-23T13:19:00Z',
      cancelledAt: '2026-10-23T13:40:00Z',
      coordinationPhone: '0300 123 4567',
    });
  });

  it('reads the back end’s own closed bodies', async () => {
    const shapes = await import('@/test/fixtures/backend-shapes');
    expect(parseClosed(shapes.LINK_CLOSED_CANCELLED)).toMatchObject({
      state: 'cancelled',
      kind: 'booking',
      reference: '4821',
      cancelledAt: '2026-10-30T14:04:00Z',
      coordinationPhone: '0300 123 4567',
    });
    expect(parseClosed(shapes.LINK_CLOSED_EXPIRED)).toMatchObject({ state: 'expired', kind: 'booking', cancelledAt: null });
    expect(parseClosed(shapes.LINK_CLOSED_UNKNOWN)).toEqual({
      state: 'expired',
      kind: null,
      reference: null,
      closedAt: null,
      confirmedAt: null,
      cancelledAt: null,
      coordinationPhone: null,
    });
  });

  it('reads a bare state word as a closed link that says nothing more', () => {
    expect(parseClosed({ state: 'used' })).toEqual({
      state: 'used',
      kind: null,
      reference: null,
      closedAt: null,
      confirmedAt: null,
      cancelledAt: null,
      coordinationPhone: null,
    });
  });

  it('reads a state it does not know as expired, and anything that is not a body as expired', () => {
    expect(parseClosed({ state: 'something-else' }).state).toBe('expired');
    expect(parseClosed(null).state).toBe('expired');
    expect(parseClosed('expired').state).toBe('expired');
    expect(parseClosed([]).state).toBe('expired');
  });

  it('drops a time that is not a time, a number that is not a number and a kind it does not know, without refusing the page', () => {
    const closed = parseClosed({
      state: 'expired',
      kind: 'capacity',
      reference: 'not a reference',
      closedAt: 'yesterday',
      confirmedAt: 17,
      cancelledAt: null,
      coordinationPhone: 'call <b>me</b>',
    });
    expect(closed).toEqual({
      state: 'expired',
      kind: null,
      reference: null,
      closedAt: null,
      confirmedAt: null,
      cancelledAt: null,
      coordinationPhone: null,
    });
  });

  it('drops every field it does not read', () => {
    const closed = parseClosed({ state: 'expired', postcode: 'DT4 8XX', name: 'Sample Patient', caseId: 'case-1001' });
    expect(JSON.stringify(closed)).not.toMatch(/DT4|Sample Patient|case-1001/);
  });
});
