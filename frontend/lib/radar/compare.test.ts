import { describe, expect, it } from 'vitest';
import { HOSPITAL_AT_HOME, UCR_EAST, UCR_WEST, WARD_B } from '@/test/fixtures/radar';
import { ageText, freeText, NOT_RECORDED, reachText } from './compare';

describe('the compare view words', () => {
  it('free: the figure with its unit, the excess when over capacity, or phone to confirm', () => {
    expect(freeText(UCR_WEST)).toBe('4 referrals in the next 2 hrs');
    expect(freeText(WARD_B)).toBe('5 beds');
    expect(freeText(HOSPITAL_AT_HOME)).toBe('+2 over');
    expect(freeText({ ...UCR_WEST, effectiveAvailable: null })).toBe('Phone to confirm');
    expect(freeText({ ...UCR_WEST, unitLabel: null })).toBe('4');
  });

  it('time to reach: the range as sent, capitalised, or not recorded (never a guess)', () => {
    expect(reachText(UCR_WEST)).toBe('About 25 to 35 min');
    expect(reachText(HOSPITAL_AT_HOME)).toBe(NOT_RECORDED);
  });

  it('data age: the age, with a warning past two hours, or not known', () => {
    expect(ageText(UCR_WEST)).toBe('9 min');
    expect(ageText(UCR_EAST)).toBe('31 min');
    expect(ageText(WARD_B)).toBe('2 hrs 15 min. Over 2 hrs old: consider phoning.');
    expect(ageText({ ...UCR_WEST, dataAgeSeconds: null })).toBe('Not known');
  });
});
