import { describe, expect, it } from 'vitest';
import { isUkMobile } from './ukMobile';

describe('isUkMobile', () => {
  it('accepts a UK mobile written nationally or internationally', () => {
    expect(isUkMobile('07700 900123')).toBe(true);
    expect(isUkMobile('+447700900123')).toBe(true);
  });

  it('refuses a short number and a landline', () => {
    expect(isUkMobile('0123')).toBe(false);
    expect(isUkMobile('01234 567890')).toBe(false);
  });
});
