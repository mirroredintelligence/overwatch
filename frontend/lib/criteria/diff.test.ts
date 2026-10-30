import { describe, expect, it } from 'vitest';
import { CRITERIA_OVERVIEW } from '@/test/fixtures/criteria';
import { diffCriteria } from './diff';
import type { CriteriaValues } from './types';

const base: CriteriaValues = {
  accepts: ['fall-no-injury', 'frailty'],
  excludes: ['suspected-fracture'],
  ageMin: 18,
  ageMax: null,
  districts: ['DT1', 'DT2'],
};

describe('diffCriteria', () => {
  it('says a changed youngest age in plain words', () => {
    expect(diffCriteria({ ...base, ageMin: 18 }, { ...base, ageMin: 16 })).toEqual(['Youngest age 18 to 16']);
  });

  it('says an added need under the list it joined', () => {
    expect(diffCriteria(base, { ...base, accepts: [...base.accepts, 'dementia'] })).toEqual(['Accepts: added Dementia']);
  });

  it('returns nothing for an unchanged set', () => {
    expect(diffCriteria(base, { ...base, accepts: [...base.accepts].reverse() })).toEqual([]);
    expect(diffCriteria(CRITERIA_OVERVIEW.current, { ...CRITERIA_OVERVIEW.current })).toEqual([]);
  });

  it('reads an oldest age that was or is now no limit', () => {
    expect(diffCriteria(base, { ...base, ageMax: 80 })).toEqual(['Oldest age No limit to 80']);
    expect(diffCriteria({ ...base, ageMax: 80 }, base)).toEqual(['Oldest age 80 to No limit']);
  });

  it('reads removed needs, excluded needs and districts, in a fixed order', () => {
    const after: CriteriaValues = {
      ...base,
      accepts: ['frailty'],
      excludes: ['infection-isolation'],
      districts: ['DT1', 'DT4'],
    };
    expect(diffCriteria(base, after)).toEqual([
      'Accepts: removed Fall, no injury',
      'Does not accept: removed Suspected fracture',
      'Does not accept: added Infection isolation',
      'Postcode districts: removed DT2',
      'Postcode districts: added DT4',
    ]);
  });
});
