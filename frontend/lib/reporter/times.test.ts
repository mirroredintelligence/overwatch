import { describe, expect, it } from 'vitest';
import { clock, inDays } from './times';

// The reporter screens show the back end's UTC instants as the tenant's clock time (domain-rules 1.4):
// London time, "HH:MM", so 08:15 is 08:15 in winter and 09:15 in British Summer Time. Anything that is not
// an instant shows as nothing, never as "Invalid Date".

describe('clock', () => {
  it('shows an instant as London time: the same hour in winter, an hour on in summer', () => {
    expect(clock('2026-10-30T08:15:00Z')).toBe('08:15');
    expect(clock('2026-07-01T10:00:00Z')).toBe('11:00');
  });

  it('crosses the clock change at the right minute', () => {
    expect(clock('2026-03-29T00:59:00Z')).toBe('00:59');
    expect(clock('2026-03-29T01:00:00Z')).toBe('02:00');
    expect(clock('2026-10-25T00:59:00Z')).toBe('01:59');
    expect(clock('2026-10-25T01:00:00Z')).toBe('01:00');
  });

  it('shows midnight as 00:00, not 24:00', () => {
    expect(clock('2026-10-30T00:00:00Z')).toBe('00:00');
  });

  it.each([null, undefined, '', 'noon', '12:00', 7])('shows %j as nothing', (value) => {
    expect(clock(value as never)).toBe('');
  });
});

describe('inDays', () => {
  it.each([
    [30, 'In 30 days'],
    [2, 'In 2 days'],
    [1, 'In 1 day'],
    [0, 'Now'],
  ])('says %i as %s', (days, text) => {
    expect(inDays(days)).toBe(text);
  });
});
