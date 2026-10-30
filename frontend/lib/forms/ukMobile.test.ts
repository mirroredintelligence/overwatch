import { describe, expect, it } from 'vitest';
import { isUkMobile, normaliseUkMobile } from './ukMobile';

describe('isUkMobile', () => {
  it.each(['07700 900456', '07700900456', '07700 900 456', '07700-900-456', '+447700900123', '+44 (0)7700 900123', '00447700900123'])(
    'accepts %s',
    (value) => {
      expect(isUkMobile(value)).toBe(true);
    },
  );

  it.each(['0123', '01234 567890', '0770090045', '077009004567', '+44770090045', 'seven'])('refuses %s', (value) => {
    expect(isUkMobile(value)).toBe(false);
  });
});

describe('normaliseUkMobile', () => {
  it('removes separators', () => {
    expect(normaliseUkMobile('07700 900456')).toBe('07700900456');
  });

  it('turns +44 and 0044 into the national form, as the back end does', () => {
    expect(normaliseUkMobile('+44 7700 900123')).toBe('07700900123');
    expect(normaliseUkMobile('+44 (0)7700 900123')).toBe('07700900123');
    expect(normaliseUkMobile('00447700900123')).toBe('07700900123');
  });
});
