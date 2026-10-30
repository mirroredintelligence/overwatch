import { describe, expect, it } from 'vitest';
import { InvalidBody, readServiceBody, toParameters } from './serviceBody';

const VALID = {
  name: 'Reablement',
  category: 'reablement',
  measure: 'referrals-acceptable',
  unitLabel: 'referrals in the next 2 hrs',
  establishedCapacity: 4,
  usualMin: 0,
  usualMax: 8,
  cadence: 'every-2-hrs',
  channel: 'text',
  mobile: '07700 900456',
  roleName: 'Duty manager',
  availableFrom: '08:00',
  availableTo: '20:00',
  ageMin: 18,
  ageMax: null,
  districts: ['DT4'],
  accepts: ['frailty'],
  excludes: [],
  reviewBy: '2031-01-31',
};

describe('readServiceBody', () => {
  it('reads a complete body', () => {
    expect(readServiceBody(structuredClone(VALID))).toMatchObject({ name: 'Reablement', ageMax: null });
  });

  it.each<[string, Record<string, unknown>]>([
    ['an unknown category', { category: 'hospital' }],
    ['an unknown measure', { measure: 'beds-in-a-cupboard' }],
    ['a time that is not HH:MM', { availableFrom: '8am' }],
    ['a review date that is not YYYY-MM-DD', { reviewBy: '31/01/2031' }],
    ['a district the back end would change', { districts: ['dt4'] }],
    ['a need that is not known', { accepts: ['everything'] }],
    ['a capacity that is not a whole number', { establishedCapacity: 2.5 }],
    ['a text channel with no mobile', { mobile: '' }],
    ['a name longer than the field allows', { name: 'x'.repeat(201) }],
  ])('refuses %s', (_label, change) => {
    expect(() => readServiceBody({ ...structuredClone(VALID), ...change })).toThrow(InvalidBody);
  });

  it('refuses a body that is not an object', () => {
    expect(() => readServiceBody('a string')).toThrow(InvalidBody);
  });
});

describe('toParameters', () => {
  it('builds a FHIR Parameters resource with one part per field, repeating districts and needs', () => {
    const parameters = toParameters(readServiceBody(structuredClone(VALID)));
    expect(parameters.resourceType).toBe('Parameters');
    const named = (name: string) => parameters.parameter.filter((p) => p.name === name);
    expect(named('name')).toEqual([{ name: 'name', valueString: 'Reablement' }]);
    expect(named('establishedCapacity')).toEqual([{ name: 'establishedCapacity', valueInteger: 4 }]);
    expect(named('category')).toEqual([{ name: 'category', valueCode: 'reablement' }]);
    expect(named('reviewBy')).toEqual([{ name: 'reviewBy', valueDate: '2031-01-31' }]);
    expect(named('district')).toHaveLength(1);
    expect(named('accepts')).toEqual([{ name: 'accepts', valueCode: 'frailty' }]);
    expect(named('excludes')).toHaveLength(0);
    expect(named('ageMax')).toHaveLength(0);
  });
});
