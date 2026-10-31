import { describe, expect, it } from 'vitest';
import { addDays, addWeeks, isMonday, lastCompleteWeekStart, weekStartQuery } from './week';

describe('isMonday', () => {
  it('is true for a real Monday and false for another day, a date that is not one, or text', () => {
    expect(isMonday('2026-10-19')).toBe(true);
    expect(isMonday('2026-10-20')).toBe(false);
    expect(isMonday('2026-02-30')).toBe(false);
    expect(isMonday('yesterday')).toBe(false);
    expect(isMonday('')).toBe(false);
  });
});

describe('lastCompleteWeekStart', () => {
  it('is the Monday of the week before this one, whatever day it is', () => {
    expect(lastCompleteWeekStart(new Date('2026-10-28T10:00:00Z'))).toBe('2026-10-19');
    expect(lastCompleteWeekStart(new Date('2026-10-26T00:00:00Z'))).toBe('2026-10-19');
    expect(lastCompleteWeekStart(new Date('2026-11-01T23:59:00Z'))).toBe('2026-10-19');
    expect(lastCompleteWeekStart(new Date('2026-11-02T00:00:00Z'))).toBe('2026-10-26');
  });
});

describe('addDays', () => {
  it('moves by days', () => {
    expect(addDays('2026-10-19', 6)).toBe('2026-10-25');
    expect(addDays('2026-12-30', 3)).toBe('2027-01-02');
  });
});

describe('addWeeks', () => {
  it('moves by whole weeks, across a month and a year', () => {
    expect(addWeeks('2026-10-19', -1)).toBe('2026-10-12');
    expect(addWeeks('2026-10-26', 1)).toBe('2026-11-02');
    expect(addWeeks('2026-12-28', 1)).toBe('2027-01-04');
  });
});

describe('weekStartQuery', () => {
  it('is ?weekStart= for a Monday, and a 400 error for anything else', () => {
    expect(weekStartQuery(new Request('https://x.test/a?weekStart=2026-10-19'))).toBe('?weekStart=2026-10-19');
    expect(() => weekStartQuery(new Request('https://x.test/a?weekStart=2026-10-20'))).toThrow();
    expect(() => weekStartQuery(new Request('https://x.test/a'))).toThrow();
  });
});
