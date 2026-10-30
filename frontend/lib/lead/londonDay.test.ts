import { describe, expect, it } from 'vitest';
import { endOfLondonDay } from './londonDay';

// A cover "until a date" ends at the end of that day in London, whatever the offset then is (DEC-654).
describe('endOfLondonDay', () => {
  it('is GMT at the end of a winter day', () => {
    expect(endOfLondonDay('2026-10-30')).toBe('2026-10-30T23:59:59+00:00');
  });

  it('is BST at the end of a summer day', () => {
    expect(endOfLondonDay('2026-06-01')).toBe('2026-06-01T23:59:59+01:00');
  });

  it('is GMT on the day the clocks go back', () => {
    expect(endOfLondonDay('2026-10-25')).toBe('2026-10-25T23:59:59+00:00');
  });

  it('refuses a date that is not a calendar date', () => {
    expect(() => endOfLondonDay('2026-13-40')).toThrow();
  });
});
