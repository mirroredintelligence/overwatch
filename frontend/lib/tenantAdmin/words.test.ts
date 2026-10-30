import { describe, expect, it } from 'vitest';
import { humaniseKey, plainAction, roleWord, stateWord, valueText, whenText } from './words';

// The words the administration and console screens print for what the back end names in codes. They take
// no tenant, say nothing clinical of their own, and name an unknown code as it is rather than invent one.

describe('whenText', () => {
  it('is London time, day month year and the clock', () => {
    expect(whenText('2026-10-21T09:00:00Z')).toBe('21 Oct 2026, 10:00');
    expect(whenText('2026-12-01T09:00:00Z')).toBe('1 Dec 2026, 09:00');
  });
  it('is a dash for no time and for text that is not one', () => {
    expect(whenText(null)).toBe('-');
    expect(whenText('soon')).toBe('-');
  });
});

describe('humaniseKey', () => {
  it('turns a setting key into words', () => {
    expect(humaniseKey('pressureWatchFrom')).toBe('Pressure watch from');
    expect(humaniseKey('twiceADaySecondTime')).toBe('Twice a day second time');
    expect(humaniseKey('systemName')).toBe('System name');
  });
});

describe('valueText', () => {
  const int = { kind: 'int', unit: 'minutes' } as const;
  it('says a value with its unit, a time as it is, a list in order and an absent value as the default', () => {
    expect(valueText(int, 30)).toBe('30 minutes');
    expect(valueText({ kind: 'int', unit: 'count' }, 3)).toBe('3');
    expect(valueText({ kind: 'time', unit: 'time-of-day' }, '14:00')).toBe('14:00');
    expect(valueText({ kind: 'codes', unit: 'codes' }, ['a', 'b'])).toBe('a, b');
    expect(valueText({ kind: 'codes', unit: 'codes' }, [])).toBe('none');
    expect(valueText({ kind: 'text', unit: 'text' }, 'Capacity A')).toBe('Capacity A');
    expect(valueText({ kind: 'bool', unit: 'flag' }, true)).toBe('on');
    expect(valueText(int, undefined)).toBe('not set');
  });
});

describe('roleWord, stateWord, plainAction', () => {
  it('names the roles of the platform’s own people', () => {
    expect(roleWord('platform-operator')).toBe('Platform operator');
    expect(roleWord('support')).toBe('Support');
    expect(roleWord('mystery')).toBe('mystery');
  });
  it('names every ticket state in a word', () => {
    expect(stateWord('pending')).toBe('Waiting for you');
    expect(stateWord('approved')).toBe('Approved, code not used yet');
    expect(stateWord('opened')).toBe('Open now');
    expect(stateWord('expired')).toBe('Lapsed');
    expect(stateWord('what')).toBe('what');
  });
  it('says what a platform step was in plain words, and an unknown one as it is', () => {
    expect(plainAction('SuspendTenant')).toBe('Suspended your organisation');
    expect(plainAction('OpenCrossTenantAccess')).toBe('Opened access with a support code');
    expect(plainAction('Nothing')).toBe('Nothing');
  });
});
