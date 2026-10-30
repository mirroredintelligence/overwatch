import { describe, expect, it } from 'vitest';
import { normalisePostcode } from './postcode';

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
