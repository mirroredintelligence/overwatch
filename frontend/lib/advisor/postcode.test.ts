import { describe, expect, it } from 'vitest';
import { normalisePostcode, outwardCode } from './postcode';

describe('normalisePostcode (W11)', () => {
  it.each([
    ['dt48xx', 'DT4 8XX'],
    [' DT4 8XX ', 'DT4 8XX'],
    ['dt4  8xx', 'DT4 8XX'],
    ['DT48XX', 'DT4 8XX'],
    ['sw1a 1aa', 'SW1A 1AA'],
  ])('%j becomes %j', (input, expected) => {
    expect(normalisePostcode(input)).toBe(expected);
  });

  it.each(['DT4 8X', 'DT4 8XXX', '', '   ', '12345', 'DT4 8X1'])('%j is not a full postcode', (input) => {
    expect(normalisePostcode(input)).toBeNull();
  });
});

describe('outwardCode (DEC-1372)', () => {
  it('gives the outward code of a postcode or a district, and null for anything else', () => {
    expect(outwardCode('DT4 8XX')).toBe('DT4');
    expect(outwardCode('dt48xx')).toBe('DT4');
    expect(outwardCode(' BH7 ')).toBe('BH7');
    expect(outwardCode('SW1A 1AA')).toBe('SW1A');
    expect(outwardCode('Weymouth')).toBeNull();
    expect(outwardCode('')).toBeNull();
    expect(outwardCode(null)).toBeNull();
  });
});
