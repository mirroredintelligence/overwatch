import { describe, expect, it } from 'vitest';
import { districtCheckFrom, typedDistricts } from './postcodeDistricts';

// The back end's district answer is read, never trusted as it arrives (DEC-1329): a count that is not a
// whole number is an unreadable answer, not a guessed count.

describe('the district check answer', () => {
  it('reads a prefix and a whole count', () => {
    expect(districtCheckFrom({ prefix: 'DT4 0', postcodes: 310 })).toEqual({ prefix: 'DT4 0', postcodes: 310 });
  });

  it('refuses a count that is not a whole, non-negative number', () => {
    expect(districtCheckFrom({ prefix: 'DT4', postcodes: 1.5 })).toBeNull();
    expect(districtCheckFrom({ prefix: 'DT4', postcodes: -1 })).toBeNull();
    expect(districtCheckFrom({ prefix: 'DT4', postcodes: '12' })).toBeNull();
    expect(districtCheckFrom({ prefix: 'DT4' })).toBeNull();
  });

  it('refuses a prefix that is not text, empty or too long', () => {
    expect(districtCheckFrom({ prefix: 7, postcodes: 1 })).toBeNull();
    expect(districtCheckFrom({ prefix: '', postcodes: 1 })).toBeNull();
    expect(districtCheckFrom({ prefix: 'DT4 0AW 9X', postcodes: 1 })).toBeNull();
    expect(districtCheckFrom(null)).toBeNull();
  });
});

describe('the districts typed', () => {
  it('splits on commas, trims, upper-cases and drops blanks', () => {
    expect(typedDistricts(' dt4 ,  so16 0 , ,')).toEqual(['DT4', 'SO16 0']);
    expect(typedDistricts('   ')).toEqual([]);
  });
});
