import { describe, expect, it } from 'vitest';
import { blankService, toServiceBody, validateService, type ServiceValues } from './serviceForm';

const TODAY = Date.parse('2026-10-30T09:00:00Z');

function valid(): ServiceValues {
  return {
    ...blankService(),
    name: 'Reablement',
    category: 'reablement',
    measure: 'referrals-acceptable',
    establishedCapacity: '4',
    cadence: 'every-2-hrs',
    channel: 'text',
    mobile: '07700 900456',
    roleName: 'Duty manager',
    allDay: false,
    days: ['0', '1', '2', '3', '4', '5', '6'],
    availableFrom: '08:00',
    availableTo: '20:00',
    ageMin: '18',
    ageMax: '',
    districts: 'DT4',
    accepts: ['frailty'],
    excludes: [],
    reviewBy: '2031-01-31',
  };
}

describe('validateService', () => {
  it('accepts a complete form', () => {
    expect(validateService(valid(), TODAY)).toEqual([]);
  });

  it('asks for the service name, the category and the needs', () => {
    const errors = validateService({ ...valid(), name: ' ', category: null, accepts: [] }, TODAY);
    expect(errors).toEqual(
      expect.arrayContaining([
        { field: 'lead-add-name', message: 'Enter the service name' },
        { field: 'lead-add-category', message: 'Choose a category' },
        { field: 'lead-add-accepts', message: 'Choose at least one need' },
      ]),
    );
  });

  it('refuses a mobile that is not a UK mobile, and says the example', () => {
    expect(validateService({ ...valid(), mobile: '0123' }, TODAY)).toEqual([
      { field: 'lead-add-mobile', message: 'Enter a UK mobile number, like 07700 900456' },
    ]);
  });

  it('asks for an email on the email channel and checks its shape', () => {
    expect(validateService({ ...valid(), channel: 'email', mobile: '', email: '' }, TODAY)).toEqual([
      { field: 'lead-add-email', message: 'Enter an email address' },
    ]);
  });

  it('takes all day with no times, and refuses no days chosen', () => {
    expect(validateService({ ...valid(), allDay: true, availableFrom: '', availableTo: '' }, TODAY)).toEqual([]);
    expect(validateService({ ...valid(), days: [] }, TODAY)).toEqual([
      { field: 'lead-add-days', message: 'Choose at least one day' },
    ]);
  });

  it('needs From and To only when the service is not all day', () => {
    expect(validateService({ ...valid(), availableFrom: '', availableTo: '' }, TODAY).map((e) => e.field)).toEqual([
      'lead-add-from',
      'lead-add-to',
    ]);
  });

  it('refuses a review date that is not in the future', () => {
    expect(validateService({ ...valid(), reviewBy: '2026-10-30' }, TODAY)).toEqual([
      { field: 'lead-add-review', message: 'Enter a review date in the future' },
    ]);
  });

  it('refuses a postcode district that the back end would change', () => {
    expect(validateService({ ...valid(), districts: 'dt4' }, TODAY)).toEqual([
      { field: 'lead-add-districts', message: 'Enter a postcode district, like DT4' },
    ]);
  });
});

describe('toServiceBody', () => {
  it('sends the phone as given, and no other personal detail beyond the form', () => {
    const body = toServiceBody(valid());
    expect(body).toMatchObject({
      name: 'Reablement',
      category: 'reablement',
      channel: 'text',
      mobile: '07700 900456',
      districts: ['DT4'],
      accepts: ['frailty'],
      excludes: [],
      ageMin: 18,
      ageMax: null,
      establishedCapacity: 4,
      allDay: false,
      days: [0, 1, 2, 3, 4, 5, 6],
    });
    expect(body).not.toHaveProperty('email');
  });
});
