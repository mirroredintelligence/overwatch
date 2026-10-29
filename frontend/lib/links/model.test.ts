import { describe, expect, it } from 'vitest';
import {
  londonHm,
  LinkShapeError,
  parseLinkAnswered,
  parseLinkView,
  parseThanks,
  splitUnitLabel,
  thanksQuery,
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

describe('thanks address', () => {
  const ANSWER = {
    serviceName: 'UCR West',
    value: 4,
    unitLabel: 'referrals in the next 2 hrs',
    recordedAt: '2026-10-23T09:12:00Z',
    nextDue: '2026-10-23T11:00:00Z',
  };

  it('carries the answer to the thank-you page and reads it back', () => {
    const query = thanksQuery(ANSWER);
    expect(parseThanks(new URLSearchParams(query.toString()))).toEqual({
      serviceName: 'UCR West',
      value: 4,
      unitLabel: 'referrals in the next 2 hrs',
      recordedAt: '2026-10-23T09:12:00Z',
      nextDue: '2026-10-23T11:00:00Z',
    });
  });

  it('reads nothing from an address that does not carry a whole, valid answer', () => {
    expect(parseThanks(new URLSearchParams())).toBeNull();
    expect(parseThanks(new URLSearchParams('value=1000&serviceName=A&unit=b&at=2026-10-23T09:12:00Z'))).toBeNull();
    expect(parseThanks(new URLSearchParams('value=4&serviceName=A&unit=b&at=not-a-time'))).toBeNull();
  });

  it('refuses a service name that is too long to be a name', () => {
    expect(parseThanks(new URLSearchParams(`value=4&serviceName=${'A'.repeat(121)}&unit=b&at=2026-10-23T09:12:00Z`))).toBeNull();
  });
});
