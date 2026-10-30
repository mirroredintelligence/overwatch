import { describe, expect, it } from 'vitest';
import { formatCount, formatMinutes, formatPct } from './weekFormat';

describe('formatCount', () => {
  it('says "fewer than 10" for a withheld count, and never a number', () => {
    expect(formatCount({ value: null, suppressed: true })).toBe('fewer than 10');
  });

  it('shows a shown count as it is', () => {
    expect(formatCount({ value: 640 })).toBe('640');
  });
});

describe('formatPct', () => {
  it('never renders a percentage for a withheld value', () => {
    expect(formatPct({ value: 18, suppressed: true })).toBe('fewer than 10');
    expect(formatPct({ value: 18, suppressed: true })).not.toContain('%');
  });

  it('shows a shown percentage, rounded to a whole number', () => {
    expect(formatPct({ value: 18.4 })).toBe('18%');
    expect(formatPct({ value: 92 })).toBe('92%');
  });

  it('says there is no figure when the value is missing and not withheld', () => {
    expect(formatPct({ value: null })).toBe('No figure yet');
  });
});

describe('formatMinutes', () => {
  it('shows whole minutes with the unit', () => {
    expect(formatMinutes(4)).toBe('4 min');
  });
});
