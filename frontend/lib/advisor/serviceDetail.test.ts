import { describe, expect, it } from 'vitest';
import {
  ServiceDetailParseError,
  catchmentText,
  criteriaLabels,
  detailAsOption,
  openingHoursLines,
  parseServiceDetail,
} from './serviceDetail';

// The read behind the service detail page (DEC-1366): parsed strictly, so a malformed answer is an error and never a
// drawn guess; a number or a time that is not held stays null and is never made up.

const ANSWER = {
  serviceId: 'svc-a',
  name: 'Ward A',
  category: 'inpatient-beds',
  status: 'limited',
  unitLabel: 'beds',
  established: 10,
  effectiveAvailable: 2,
  overBy: null,
  lastFigure: 2,
  reportedAt: '2026-10-30T06:30:00Z',
  nextDueAt: '2026-10-30T08:30:00Z',
  cadence: 'every-2-hrs',
  overdue: false,
  staleWarning: false,
  dataAgeSeconds: 1800,
  phone: '01305 000000',
  openingHours: [
    { days: [0, 1, 2, 3, 4], allDay: false, start: '08:00', end: '18:00' },
    { days: [5, 6], allDay: true, start: null, end: null },
  ],
  accepts: ['frailty', 'wound-care'],
  excludes: ['iv-therapy'],
  ageMin: 18,
  ageMax: null,
  districts: ['DT4', 'DT5'],
};

describe('parseServiceDetail', () => {
  it('reads the answer', () => {
    const detail = parseServiceDetail(ANSWER);
    expect(detail.name).toBe('Ward A');
    expect(detail.established).toBe(10);
    expect(detail.phone).toBe('01305 000000');
    expect(detail.districts).toEqual(['DT4', 'DT5']);
  });

  it.each([null, 'x', [], {}, { ...ANSWER, name: '' }, { ...ANSWER, status: 'fine' }, { ...ANSWER, established: -1 }])(
    'refuses an answer that is not the shape it knows: %j',
    (value) => {
      expect(() => parseServiceDetail(value)).toThrow(ServiceDetailParseError);
    },
  );

  it('drops a phone that is not a number it would offer to dial, and keeps nothing it does not know', () => {
    expect(parseServiceDetail({ ...ANSWER, phone: 'javascript:alert(1)' }).phone).toBeNull();
    expect(parseServiceDetail({ ...ANSWER, phone: null }).phone).toBeNull();
    const detail = parseServiceDetail({ ...ANSWER, email: 'a@b.test', mobile: '07700 900123' });
    expect(JSON.stringify(detail)).not.toMatch(/@|07700/);
  });

  it('keeps no criteria as null, not as an empty list that reads as "none"', () => {
    const detail = parseServiceDetail({ ...ANSWER, accepts: null, excludes: null, ageMin: null });
    expect(detail.accepts).toBeNull();
    expect(detail.excludes).toBeNull();
  });
});

describe('detailAsOption', () => {
  it('is a current figure when the report is on time', () => {
    const option = detailAsOption(parseServiceDetail(ANSWER));
    expect(option.figureUnavailable).toBe(false);
    expect(option.effectiveAvailable).toBe(2);
  });

  it.each([{ overdue: true }, { staleWarning: true }, { status: 'not-updated' }, { dataAgeSeconds: 3 * 60 * 60 }])(
    'is an unavailable figure when %j',
    (change) => {
      expect(detailAsOption(parseServiceDetail({ ...ANSWER, ...change })).figureUnavailable).toBe(true);
    },
  );
});

describe('words', () => {
  it('writes opening hours in plain lines', () => {
    expect(openingHoursLines(parseServiceDetail(ANSWER).openingHours)).toEqual([
      'Mon to Fri, 08:00 to 18:00',
      'Sat and Sun, all day',
    ]);
    expect(openingHoursLines([{ days: [0, 1, 2, 3, 4, 5, 6], allDay: true, start: null, end: null }])).toEqual([
      'Every day, all day',
    ]);
  });

  it('turns need codes into labels, and refuses a code it does not know', () => {
    expect(criteriaLabels(['frailty', 'wound-care'])).toEqual(['Frailty', 'Wound care']);
    expect(criteriaLabels(['nonsense'])).toBeNull();
    expect(criteriaLabels(null)).toBeNull();
  });

  it('writes the catchment, and says none when there are no districts', () => {
    expect(catchmentText(['DT4', 'DT5'])).toBe('DT4, DT5');
    expect(catchmentText([])).toBeNull();
  });
});
