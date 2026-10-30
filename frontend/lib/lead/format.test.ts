import { describe, expect, it } from 'vitest';
import { agoText, clockTime, overdueText } from './format';

describe('overdueText', () => {
  it('says hours and minutes, as the card does', () => {
    expect(overdueText(132)).toBe('2 hrs 12 min');
  });

  it('says minutes alone under an hour', () => {
    expect(overdueText(50)).toBe('50 min');
  });

  it('drops zero minutes and uses the singular for one hour', () => {
    expect(overdueText(60)).toBe('1 hr');
    expect(overdueText(120)).toBe('2 hrs');
  });
});

describe('clockTime', () => {
  it('reads the instant in London time: GMT after the clocks go back', () => {
    expect(clockTime('2026-10-30T12:00:00Z')).toBe('12:00');
  });

  it('reads the instant in London time: BST before the clocks go back', () => {
    expect(clockTime('2026-10-23T07:15:00Z')).toBe('08:15');
  });
});

describe('agoText', () => {
  it('says how long ago an instant was, against the given now', () => {
    expect(agoText('2026-10-30T14:50:00Z', Date.parse('2026-10-30T17:00:00Z'))).toBe('2 hrs 10 min ago');
  });
});
