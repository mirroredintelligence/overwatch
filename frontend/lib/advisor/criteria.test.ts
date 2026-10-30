import { describe, expect, it } from 'vitest';
import { CRITERIA_HISTORY } from '@/test/fixtures/backend-shapes';
import { criteriaFromHistory } from './criteria';

// The criteria history as the back end answers it to an advisor (routes_criteria.py `_view_basic`): the
// current version only, with what it accepts and excludes and the age range. The author and the day of
// the change are not sent to an advisor, so the dialog says "not recorded" for them.

describe('criteriaFromHistory (W14)', () => {
  it('shows what the current version accepts and excludes, in words, with the age range', () => {
    expect(criteriaFromHistory(CRITERIA_HISTORY, '2026-10-30')).toEqual({
      accepts: 'Fall, no injury · Frailty · Age 18+',
      excludes: 'Suspected fracture',
      version: 3,
      reviewedOn: null,
      reviewBy: '2026-12-12',
      owner: null,
      overdue: false,
    });
  });

  it('words a closed age range, and says so when nothing is excluded', () => {
    const bundle = {
      resourceType: 'Bundle',
      entry: [{ resource: { ...CRITERIA_HISTORY.entry[0]!.resource, ageMin: 16, ageMax: 64, excludes: [] } }],
    };
    expect(criteriaFromHistory(bundle, '2026-10-30')).toMatchObject({
      accepts: 'Fall, no injury · Frailty · Age 16 to 64',
      excludes: 'None listed',
    });
  });

  it('flags a review date before today as overdue, and not today itself', () => {
    expect(criteriaFromHistory(CRITERIA_HISTORY, '2026-12-13')?.overdue).toBe(true);
    expect(criteriaFromHistory(CRITERIA_HISTORY, '2026-12-12')?.overdue).toBe(false);
  });

  it('does not guess when a need code is not one the rules list: it is left out and the dialog tells the advisor to phone', () => {
    const bundle = {
      resourceType: 'Bundle',
      entry: [{ resource: { ...CRITERIA_HISTORY.entry[0]!.resource, accepts: ['frailty', 'mystery'] } }],
    };
    expect(criteriaFromHistory(bundle, '2026-10-30')?.accepts).toBeNull();
  });

  it('has none for a service with no current version', () => {
    expect(criteriaFromHistory({ resourceType: 'Bundle', entry: [] }, '2026-10-30')).toBeNull();
    expect(criteriaFromHistory(null, '2026-10-30')).toBeNull();
  });
});
