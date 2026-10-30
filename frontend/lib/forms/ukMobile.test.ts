import { describe, expect, it } from 'vitest';
import { isUkMobile, normaliseUkMobile } from './ukMobile';

describe('isUkMobile', () => {
  it.each(['07700 900456', '07700900456', '07700 900 456'])('accepts %s', (value) => {
    expect(isUkMobile(value)).toBe(true);
  });

  it.each(['0123', '+447700900456', '0770090045', '077009004567', 'seven'])('refuses %s', (value) => {
    expect(isUkMobile(value)).toBe(false);
  });

  it('normalises by removing spaces only', () => {
    expect(normaliseUkMobile('07700 900456')).toBe('07700900456');
  });
});
