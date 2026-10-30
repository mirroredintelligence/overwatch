import { describe, expect, it } from 'vitest';
import { LINE_CONTACT, NO_CONTACT, SEEN_NO_DISPLAY, SEEN_NONE_FITTED, SEEN_SHOWN, SEEN_UNREADABLE, WORK_PHONE_CONTACT } from '@/test/msw/handlers/clinical';
import { advisorContactFromJson, seenFromJson, seenLineText } from './seen';

// What the advisor saw and the way to reach the advisor, as the back end sends them (W9G).

describe('seenFromJson', () => {
  it('reads a display: the time, the count of options and one line per service, as sent', () => {
    const seen = seenFromJson(SEEN_SHOWN);
    expect(seen.state).toBe('shown');
    expect(seen.shownAt).toBe('2026-10-23T13:13:20Z');
    expect(seen.options).toBe(2);
    expect(seen.lines.map((line) => line.service)).toEqual(['UCR West', 'Hospital at home', 'Ward B', 'UCR East']);
    expect(seen.lines[1]).toMatchObject({ statusText: 'Over capacity', figure: '+2', stale: false });
    expect(seen.lines[3]).toMatchObject({ shownAs: 'not-suitable', figure: null, why: 'Not accepting' });
  });

  it('reads a display where nothing fitted, still listing what was considered', () => {
    const seen = seenFromJson(SEEN_NONE_FITTED);
    expect(seen.noneFitted).toBe(true);
    expect(seen.lines).toHaveLength(2);
  });

  it('reads no display kept and a display that cannot be read as states with no lines', () => {
    expect(seenFromJson(SEEN_NO_DISPLAY)).toMatchObject({ state: 'none', shownAt: null, lines: [] });
    expect(seenFromJson(SEEN_UNREADABLE)).toMatchObject({ state: 'unreadable', shownAt: null, lines: [] });
  });

  it.each([
    ['a state that is not known', { ...SEEN_SHOWN, state: 'maybe' }],
    ['a shown display with no time', { ...SEEN_SHOWN, shownAt: null }],
    ['lines that are not a list', { ...SEEN_SHOWN, lines: 'UCR West' }],
    ['a state with lines it should not have', { ...SEEN_NO_DISPLAY, lines: SEEN_SHOWN.lines }],
    ['a line with no service', { ...SEEN_SHOWN, lines: [{ ...SEEN_SHOWN.lines[0], service: '' }] }],
    ['a line shown as something else', { ...SEEN_SHOWN, lines: [{ ...SEEN_SHOWN.lines[0], shownAs: 'maybe' }] }],
    ['a line with a status that is not known', { ...SEEN_SHOWN, lines: [{ ...SEEN_SHOWN.lines[0], status: 'made-up' }] }],
    ['a figure that is a number and not text', { ...SEEN_SHOWN, lines: [{ ...SEEN_SHOWN.lines[0], figure: 4 }] }],
    ['a line with no age', { ...SEEN_SHOWN, lines: [{ ...SEEN_SHOWN.lines[0], age: undefined }] }],
    ['a stale flag that is not true or false', { ...SEEN_SHOWN, lines: [{ ...SEEN_SHOWN.lines[0], stale: 'no' }] }],
    ['a count of options that is not a number', { ...SEEN_SHOWN, options: '2' }],
    ['something that is not an object', 'shown'],
  ])('refuses %s, so half a display is never shown', (_name, body) => {
    expect(() => seenFromJson(body)).toThrow();
  });

  it('keeps nothing the back end sends beyond the fields it knows (no identifier, no postcode)', () => {
    const seen = seenFromJson({ ...SEEN_SHOWN, postcode: 'DT4 8XX', lines: SEEN_SHOWN.lines.map((line) => ({ ...line, serviceId: 'svc-1', district: 'DT4' })) });
    expect(JSON.stringify(seen)).not.toMatch(/DT4|svc-1|postcode|district/);
  });
});

describe('seenLineText', () => {
  const lines = seenFromJson(SEEN_SHOWN).lines;

  it('reads as the advisor saw it: service, status, figure, how old', () => {
    expect(seenLineText(lines[0]!)).toBe('UCR West: accepting, 4, 9 min old');
    expect(seenLineText(lines[1]!)).toBe('Hospital at home: over capacity, +2, 14 min old');
  });

  it('says in words that a figure is old, so it is not colour alone', () => {
    expect(seenLineText(lines[2]!)).toBe('Ward B: accepting, 5, 2 hrs 10 min old. Over 2 hrs old.');
  });

  it('says a service was not suitable and why, and does not say it twice when the reason is the status', () => {
    expect(seenLineText(lines[3]!)).toBe('UCR East: not accepting, 3 min old. Not suitable.');
    const outside = seenFromJson(SEEN_NONE_FITTED).lines[1]!;
    expect(seenLineText(outside)).toBe('Ward B: accepting, 5, 1 min old. Not suitable: outside its criteria.');
  });

  it('says there is no figure rather than leaving it out when a service has none and is an option', () => {
    const line = { ...lines[0]!, figure: null, status: 'limited', statusText: 'Limited' };
    expect(seenLineText(line)).toBe('UCR West: limited, no figure, 9 min old');
  });
});

describe('advisorContactFromJson', () => {
  it('reads the advisor’s work phone with their name', () => {
    expect(advisorContactFromJson(WORK_PHONE_CONTACT)).toEqual({ via: 'work-phone', phone: '07700 900123', name: 'Sample Advisor' });
  });

  it('reads the advisor line, with no name', () => {
    expect(advisorContactFromJson(LINE_CONTACT)).toEqual({ via: 'advisor-line', phone: '01305 900000', name: null });
  });

  it('reads no number as none', () => {
    expect(advisorContactFromJson(NO_CONTACT)).toEqual({ via: null, phone: null, name: null });
  });

  it.each([
    ['available with no number', { ...WORK_PHONE_CONTACT, phone: null }],
    ['available with no way', { ...WORK_PHONE_CONTACT, via: null }],
    ['a way that is not known', { ...WORK_PHONE_CONTACT, via: 'text' }],
    ['not available with a number', { ...NO_CONTACT, phone: '07700 900123' }],
    ['a number that is not a phone number', { ...WORK_PHONE_CONTACT, phone: 'call me on ext 4' }],
    ['a number with markup in it', { ...WORK_PHONE_CONTACT, phone: '<b>07700 900123</b>' }],
    ['an available flag that is not true or false', { ...WORK_PHONE_CONTACT, available: 'yes' }],
    ['something that is not an object', null],
  ])('refuses %s', (_name, body) => {
    expect(() => advisorContactFromJson(body)).toThrow();
  });
});
