import { describe, expect, it } from 'vitest';
import { londonDayMonthTime, londonHourMinute } from './time';

// Times on the registration status pages are shown in London time, as the screens say (W27).

describe('londonDayMonthTime', () => {
  it('shows the day, the short month and the London time, in summer time', () => {
    // 14:30 BST on 23 October is 13:30 UTC.
    expect(londonDayMonthTime('2026-10-23T13:30:00Z')).toBe('23 Oct 14:30');
  });

  it('shows London time in winter, after the clocks change', () => {
    expect(londonDayMonthTime('2026-10-30T13:30:00Z')).toBe('30 Oct 13:30');
  });
});

describe('londonHourMinute', () => {
  it('shows the London hour and minute with a colon', () => {
    expect(londonHourMinute('2026-10-30T15:00:00Z')).toBe('15:00');
    expect(londonHourMinute('2026-10-23T15:00:00Z')).toBe('16:00');
  });
});
