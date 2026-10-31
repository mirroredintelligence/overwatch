import { describe, expect, it } from 'vitest';
import { isWindow, overlapWith, parseCoverage, parseCoverageForm, problemsOf, summariseCoverage } from './types';

const VIEW = {
  window: 'night',
  districts: [
    { district: 'DT3', services: ['UCR West', 'UCR East'] },
    { district: 'DT4', services: ['UCR West', 'UCR East'] },
    { district: 'DT5', services: [] },
    { district: 'DT6', services: [] },
    { district: 'DT1', services: ['UCR West'] },
  ],
  uncovered: { count: 31, suppressed: false, days: 90 },
};

describe('parseCoverage', () => {
  it('reads the answer and keeps only what the screen shows', () => {
    const view = parseCoverage({ ...VIEW, extra: 'x', districts: VIEW.districts.map((entry) => ({ ...entry, note: 'x' })) });
    expect(view).toEqual(VIEW);
  });

  it('summarises the districts with no cover and with two or more, in the order sent', () => {
    expect(summariseCoverage(parseCoverage(VIEW)!)).toEqual({ none: ['DT5', 'DT6'], twoOrMore: ['DT3', 'DT4'] });
  });

  it('a withheld count has no number, and a number has no withheld flag', () => {
    expect(parseCoverage({ ...VIEW, uncovered: { count: null, suppressed: true, days: 90 } })?.uncovered).toEqual({ count: null, suppressed: true, days: 90 });
    expect(parseCoverage({ ...VIEW, uncovered: { count: 3, suppressed: true, days: 90 } })).toBeNull();
    expect(parseCoverage({ ...VIEW, uncovered: { count: null, suppressed: false, days: 90 } })).toBeNull();
  });

  it.each([
    ['not an object', 'text'],
    ['an unknown window', { ...VIEW, window: 'noon' }],
    ['a district that is not a district', { ...VIEW, districts: [{ district: 'dt3', services: [] }] }],
    ['services that are not names', { ...VIEW, districts: [{ district: 'DT3', services: [1] }] }],
    ['no uncovered block', { ...VIEW, uncovered: undefined }],
    ['days that are not a count', { ...VIEW, uncovered: { count: 31, suppressed: false, days: 0 } }],
  ])('refuses %s', (_name, value) => {
    expect(parseCoverage(value)).toBeNull();
  });

  it('knows the windows it offers', () => {
    expect(isWindow('all')).toBe(true);
    expect(isWindow('evening')).toBe(true);
    expect(isWindow('noon')).toBe(false);
    expect(isWindow(null)).toBe(false);
  });
});

const FORM = {
  service: { id: 'svc-ucr-west', name: 'UCR West' },
  available: ['DT1', 'DT2', 'DT3', 'DT4', 'DT5', 'DT6'],
  districts: ['DT3', 'DT4'],
  responseHours: 2,
  days: ['mon', 'tue', 'wed', 'thu', 'fri'],
  others: [
    { district: 'DT4', service: 'UCR East' },
    { district: 'DT5', service: 'UCR East' },
  ],
};

describe('parseCoverageForm', () => {
  it('reads the form', () => {
    expect(parseCoverageForm(FORM)).toEqual({
      serviceId: 'svc-ucr-west',
      serviceName: 'UCR West',
      available: FORM.available,
      districts: ['DT3', 'DT4'],
      responseHours: 2,
      days: FORM.days,
      others: FORM.others,
    });
  });

  it('drops a chosen district that is not on offer, and a response target out of range is unset', () => {
    const form = parseCoverageForm({ ...FORM, districts: ['DT3', 'DT9'], responseHours: 500 });
    expect(form?.districts).toEqual(['DT3']);
    expect(form?.responseHours).toBeNull();
  });

  it.each([
    ['no service', { ...FORM, service: undefined }],
    ['a bad district on offer', { ...FORM, available: ['nope'] }],
    ['a day that is not a day', { ...FORM, days: ['funday'] }],
    ['others that are not a list', { ...FORM, others: 'x' }],
  ])('refuses %s', (_name, value) => {
    expect(parseCoverageForm(value)).toBeNull();
  });

  it('names the other services that cover a chosen district, once each', () => {
    const form = parseCoverageForm(FORM)!;
    expect(overlapWith(form, ['DT3', 'DT4'])).toEqual([{ service: 'UCR East', districts: ['DT4'] }]);
    expect(overlapWith(form, ['DT4', 'DT5'])).toEqual([{ service: 'UCR East', districts: ['DT4', 'DT5'] }]);
    expect(overlapWith(form, ['DT1'])).toEqual([]);
  });
});

describe('problemsOf', () => {
  const ok = { districts: ['DT3'], responseHours: '2', days: ['mon' as const] };

  it('a complete form has no problem', () => {
    expect(problemsOf(ok)).toEqual([]);
  });

  it('reports each missing part in the order the form reads', () => {
    expect(problemsOf({ districts: [], responseHours: '', days: [] })).toEqual(['districts', 'hours', 'days']);
  });

  it.each(['0', '73', '1.5', 'two', '-1', ''])('refuses %j as a response target', (hours) => {
    expect(problemsOf({ ...ok, responseHours: hours })).toEqual(['hours']);
  });

  it.each(['1', '24', '72', ' 2 '])('accepts %j as a response target', (hours) => {
    expect(problemsOf({ ...ok, responseHours: hours })).toEqual([]);
  });
});
