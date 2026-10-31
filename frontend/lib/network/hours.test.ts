import { describe, expect, it } from 'vitest';
import { hoursText } from './hours';
import type { OpeningHour } from './types';

// TEN-071: a service's opening hours in words, from the windows the organisation shared. Days are 0
// (Monday) to 6 (Sunday); times are the service's own local times, as shared.

const window = (days: number[], start: string | null, end: string | null, allDay = false, position = 0): OpeningHour => ({ position, days, allDay, start, end });

describe('hoursText', () => {
  it('writes a run of days as "Mon to Fri" with the times', () => {
    expect(hoursText([window([0, 1, 2, 3, 4], '08:00', '20:00')])).toBe('Mon to Fri 08:00 to 20:00');
  });

  it('writes seven days all day as every day, all day', () => {
    expect(hoursText([window([0, 1, 2, 3, 4, 5, 6], null, null, true)])).toBe('Every day, all day');
  });

  it('lists days that are not a run of three or more one by one', () => {
    expect(hoursText([window([0, 2, 4], '09:00', '17:00')])).toBe('Mon, Wed, Fri 09:00 to 17:00');
    expect(hoursText([window([5, 6], '09:00', '13:00')])).toBe('Sat, Sun 09:00 to 13:00');
  });

  it('joins windows, in the order of their position', () => {
    expect(hoursText([window([5, 6], '09:00', '13:00', false, 1), window([0, 1, 2, 3, 4], '08:00', '20:00', false, 0)])).toBe('Mon to Fri 08:00 to 20:00; Sat, Sun 09:00 to 13:00');
  });

  it('writes an all-day window on some days', () => {
    expect(hoursText([window([0, 1, 2], null, null, true)])).toBe('Mon to Wed, all day');
  });

  it('says so when no hours were shared, and never invents any', () => {
    expect(hoursText([])).toBe('Opening hours not shared');
  });
});
