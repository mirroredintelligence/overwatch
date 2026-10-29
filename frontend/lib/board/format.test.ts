import { describe, expect, it } from 'vitest';
import { entry, NOW, UCR_WEST, VIRTUAL_WARD } from '@/test/fixtures/board';
import {
  ageLineText,
  categoryLabel,
  dataAgeText,
  durationText,
  londonDate,
  londonTime,
  nextDueText,
  reopensText,
} from './format';

const MINUTE = 60_000;

function ago(ms: number): Date {
  return new Date(NOW.getTime() - ms);
}

describe('dataAgeText (domain-rules 1.5)', () => {
  it.each([
    ['30 seconds', 30_000, 'just now'],
    ['59 seconds', 59_000, 'just now'],
    ['1 minute', MINUTE, '1 min ago'],
    ['9 minutes', 9 * MINUTE, '9 min ago'],
    ['59 minutes', 59 * MINUTE, '59 min ago'],
    ['60 minutes', 60 * MINUTE, '1 hr ago'],
    ['65 minutes', 65 * MINUTE, '1 hr 5 min ago'],
    ['119 minutes', 119 * MINUTE, '1 hr 59 min ago'],
    ['120 minutes', 120 * MINUTE, '2 hrs ago'],
    ['130 minutes', 130 * MINUTE, '2 hrs 10 min ago'],
    ['180 minutes', 180 * MINUTE, '3 hrs ago'],
  ])('%s is "%s"', (_label, ms, expected) => {
    expect(dataAgeText(ago(ms), NOW)).toBe(expected);
  });

  it('reads whole minutes down, so 9 min 59 s is 9 min', () => {
    expect(dataAgeText(ago(9 * MINUTE + 59_000), NOW)).toBe('9 min ago');
  });

  it('accepts ISO strings as well as dates', () => {
    expect(dataAgeText('2026-10-23T13:03:00Z', '2026-10-23T13:12:00Z')).toBe('9 min ago');
  });

  it('says just now for a figure dated after the clock, never a negative age', () => {
    expect(dataAgeText('2026-10-23T13:20:00Z', NOW)).toBe('just now');
  });
});

describe('durationText', () => {
  it.each([
    [0, 'under 1 min'],
    [1, '1 min'],
    [45, '45 min'],
    [60, '1 hr'],
    [250, '4 hrs 10 min'],
    [180, '3 hrs'],
  ])('%i minutes is "%s"', (minutes, expected) => {
    expect(durationText(minutes)).toBe(expected);
  });
});

describe('londonTime and londonDate', () => {
  it('shows British Summer Time as one hour ahead of UTC', () => {
    expect(londonTime('2026-10-23T13:12:00Z')).toBe('14:12');
    expect(londonDate('2026-10-23T13:12:00Z')).toBe('Friday 23 October');
  });

  it('shows Greenwich Mean Time as UTC, after the clocks go back on 2026-10-25', () => {
    expect(londonTime('2026-10-25T00:30:00Z')).toBe('01:30'); // still BST
    expect(londonTime('2026-10-25T01:30:00Z')).toBe('01:30'); // now GMT
    expect(londonTime('2026-12-01T14:12:00Z')).toBe('14:12');
  });

  it('shows midnight as 00:00, not 24:00', () => {
    expect(londonTime('2026-10-23T23:00:00Z')).toBe('00:00');
  });

  it('takes the London date, which differs from the UTC date after 23:00 UTC in summer', () => {
    expect(londonDate('2026-10-23T23:30:00Z')).toBe('Saturday 24 October');
  });
});

describe('nextDueText', () => {
  it('shows the time for a due time on the same London day', () => {
    expect(nextDueText('2026-10-23T13:30:00Z', NOW)).toBe('next due 14:30');
  });

  it('says tomorrow for a due time on the next London day', () => {
    expect(nextDueText('2026-10-24T08:00:00Z', NOW)).toBe('next due 09:00 tomorrow');
  });

  it('compares London days, not UTC days', () => {
    // 23:30 UTC on the 23rd is 00:30 BST on the 24th: tomorrow in London.
    expect(nextDueText('2026-10-23T23:30:00Z', NOW)).toBe('next due 00:30 tomorrow');
  });

  it('names the day when the due time is more than a day away', () => {
    expect(nextDueText('2026-10-26T09:00:00Z', NOW)).toBe('next due 09:00 Monday');
  });
});

describe('reopensText (W07)', () => {
  const FRI_1412 = new Date('2026-10-23T13:12:00Z');
  const SAT_0240 = new Date('2026-10-24T01:40:00Z');

  it('reads "Reopens 08:00" when the service reopens later the same London day', () => {
    expect(reopensText('2026-10-24T07:00:00Z', SAT_0240)).toBe('Reopens 08:00');
  });

  it('adds "tomorrow" for the next London day and the weekday after that', () => {
    expect(reopensText('2026-10-24T07:00:00Z', FRI_1412)).toBe('Reopens 08:00 tomorrow');
    expect(reopensText('2026-10-26T08:00:00Z', FRI_1412)).toBe('Reopens 08:00 Monday');
  });

  it('is in London time on both sides of the autumn clock change (25 October 2026)', () => {
    // 22:30 UTC on 24 October is 23:30 BST; 08:00 UTC on 25 October is 08:00 GMT.
    expect(reopensText('2026-10-25T08:00:00Z', new Date('2026-10-24T22:30:00Z'))).toBe('Reopens 08:00 tomorrow');
    // 00:30 UTC on 25 October is 01:30 BST, the same London day as 08:00 GMT.
    expect(reopensText('2026-10-25T08:00:00Z', new Date('2026-10-25T00:30:00Z'))).toBe('Reopens 08:00');
  });
});

describe('ageLineText', () => {
  it('reads "Closed overnight" for a service that is out of hours, whatever it last reported (W07)', () => {
    const closed = entry({ serviceId: 'svc-oh', name: 'Night', status: 'out-of-hours' });
    expect(ageLineText(closed, NOW)).toBe('Closed overnight');
    expect(ageLineText({ ...closed, reportedAt: null, nextDueAt: null }, NOW)).toBe('Closed overnight');
  });

  it('reads "Updated N ago · next due" for a service that is up to date', () => {
    expect(ageLineText(UCR_WEST, NOW)).toBe('Updated 9 min ago · next due 14:30');
  });

  it('reads "Updated ... next due 09:00 tomorrow" when the next due time is on another day', () => {
    const reablement = entry({
      serviceId: 'svc-r',
      name: 'Reablement',
      reportedAt: '2026-10-23T10:12:00Z',
      nextDueAt: '2026-10-24T08:00:00Z',
    });
    expect(ageLineText(reablement, NOW)).toBe('Updated 3 hrs ago · next due 09:00 tomorrow');
  });

  it('leaves out the next due part when there is no next due time', () => {
    expect(ageLineText({ ...UCR_WEST, nextDueAt: null }, NOW)).toBe('Updated 9 min ago');
  });

  it('reads "Not updated for ... · was due" for a service that is not updated', () => {
    expect(ageLineText(VIRTUAL_WARD, NOW)).toBe('Not updated for 4 hrs 10 min · was due 12:00');
  });

  it('leaves out the was-due part when the back end gives none', () => {
    expect(ageLineText({ ...VIRTUAL_WARD, wasDueAt: null }, NOW)).toBe('Not updated for 4 hrs 10 min');
  });

  it('says no figure has been reported when a service that is not updated has no report', () => {
    expect(ageLineText({ ...VIRTUAL_WARD, reportedAt: null }, NOW)).toBe(
      'No figure reported yet · was due 12:00',
    );
  });

  it('says no figure has been reported for any status when there is no report', () => {
    expect(ageLineText({ ...UCR_WEST, reportedAt: null, nextDueAt: null }, NOW)).toBe(
      'No figure reported yet',
    );
  });
});

describe('categoryLabel', () => {
  it.each([
    ['urgent-community-response', 'Urgent community response'],
    ['same-day-emergency-care', 'Same day emergency care'],
    ['inpatient-beds', 'Inpatient beds'],
    ['hospital-at-home-or-virtual-ward', 'Virtual beds'],
    ['reablement', 'Care packages'],
    ['urgent-treatment', 'Urgent treatment'],
    ['mental-health-crisis', 'Mental health crisis'],
    ['other', 'Other'],
  ])('%s is "%s"', (code, label) => {
    expect(categoryLabel(code)).toBe(label);
  });

  it('turns a code it does not know into plain words rather than showing the code', () => {
    expect(categoryLabel('some-new-category')).toBe('Some new category');
  });
});
