import { describe, expect, it } from 'vitest';
import { parseRoster, RosterParseError, shiftWords } from './roster';

// The duty roster as the page reads it (DEC-1341).

const MANAGER = { roleId: 'role-1', name: 'Ana Duty', numberEnding: '0111', state: 'on-shift', shiftEnd: '2026-11-06T18:00:00Z' };

describe('parseRoster', () => {
  it('reads each person with their number ending and shift', () => {
    const roster = parseRoster({ managers: [MANAGER, { ...MANAGER, roleId: 'role-2', state: 'off-shift', shiftEnd: null }] });
    expect(roster.managers).toHaveLength(2);
    expect(roster.managers[1]).toMatchObject({ state: 'off-shift', shiftEnd: null });
  });

  it('reads an empty roster as empty, not as an error', () => {
    expect(parseRoster({ managers: [] })).toEqual({ managers: [] });
  });

  it('refuses a malformed answer, so a broken read is never shown as an empty roster', () => {
    expect(() => parseRoster({})).toThrow(RosterParseError);
    expect(() => parseRoster({ managers: 'no' })).toThrow(RosterParseError);
    expect(() => parseRoster({ managers: [{ ...MANAGER, state: 'removed' }] })).toThrow(RosterParseError);
    expect(() => parseRoster({ managers: [{ ...MANAGER, shiftEnd: 'not a time' }] })).toThrow(RosterParseError);
    expect(() => parseRoster({ managers: [{ ...MANAGER, name: 7 }] })).toThrow(RosterParseError);
  });
});

describe('shiftWords', () => {
  const clock = (iso: string) => `at ${iso.slice(11, 16)}`;

  it('says when a person on shift finishes, and Off shift otherwise', () => {
    const on = parseRoster({ managers: [MANAGER] }).managers[0];
    expect(shiftWords(on, clock)).toBe('On shift until at 18:00');
    expect(shiftWords({ ...on, state: 'off-shift', shiftEnd: null }, clock)).toBe('Off shift');
  });
});
