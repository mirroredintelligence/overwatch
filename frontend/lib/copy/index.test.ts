import { describe, expect, it } from 'vitest';
import { POLICY_DEFAULTS } from '@/lib/tenant/policy';
import { parseProfile } from '@/lib/tenant/profile';
import { TENANTS } from '@/test/tenants';
import { copy, duration } from './index';

// The words the pages print that depend on the tenant or on a policy number. They take the profile
// and the policy as arguments; nothing here names a place, an organisation, a system or a number of
// its own. Where a tenant has not set a word, the copy leaves the sentence out rather than invent one
// (H-T15).

const A = parseProfile(TENANTS.A.profile)!;
const C = parseProfile(TENANTS.C.profile)!;

describe('duration', () => {
  it.each([
    [1, 'minute', '1 minute'],
    [10, 'minute', '10 minutes'],
    [1, 'hour', '1 hour'],
    [48, 'hour', '48 hours'],
    [30, 'day', '30 days'],
  ] as const)('writes %i %s as %s', (n, unit, text) => {
    expect(duration(n, unit)).toBe(text);
  });

  it('refuses a count that is not a positive whole number', () => {
    for (const n of [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) expect(() => duration(n, 'minute')).toThrow();
  });
});

describe('copy.signIn', () => {
  it('names the staff account and no organisation type', () => {
    const text = copy.signIn();
    expect(text.intro).toBe('Use your staff account. There is no new password.');
    expect(text.button).toBe('Sign in with your staff account');
    expect(JSON.stringify(text)).not.toMatch(/trust|dorset|nhs|spoa/i);
  });
});

describe('copy.wallSubtitle', () => {
  it('is the tenant’s own coordination team name', () => {
    expect(copy.wallSubtitle(A)).toBe('Access team A');
  });

  it('is nothing for a tenant with no wording, and for no profile: no words are invented', () => {
    expect(copy.wallSubtitle(C)).toBeNull();
    expect(copy.wallSubtitle(null)).toBeNull();
  });
});

describe('copy.phoneTheCoordinationTeam', () => {
  it('names the team and the number the tenant gave', () => {
    expect(copy.phoneTheCoordinationTeam(A)).toBe('Phone Access team A on 01632 960001.');
  });

  it('is the team alone when there is no number, the number alone when there is no team, and nothing when there is neither', () => {
    expect(copy.phoneTheCoordinationTeam({ ...A, coordinationPhone: null })).toBe('Phone Access team A.');
    expect(copy.phoneTheCoordinationTeam({ ...A, wording: null })).toBe('Phone 01632 960001.');
    expect(copy.phoneTheCoordinationTeam(C)).toBeNull();
    expect(copy.phoneTheCoordinationTeam(null)).toBeNull();
  });

  it('prints the words as text and never as markup', () => {
    const tricky = { ...A, wording: { ...A.wording!, coordinationTeamName: '<b>Team</b>' } };
    expect(copy.phoneTheCoordinationTeam(tricky)).toBe('Phone <b>Team</b> on 01632 960001.');
  });
});

describe('copy from the policy', () => {
  it('writes the booking reply window and the prompt from the numbers, not from literals', () => {
    expect(copy.bookingReplyBy(POLICY_DEFAULTS)).toBe('Reply within 10 minutes.');
    expect(copy.bookingReplyBy({ ...POLICY_DEFAULTS, bookingReplyMinutes: 15 })).toBe('Reply within 15 minutes.');
    expect(copy.bookingPhonePrompt(POLICY_DEFAULTS)).toBe('If there is no answer after 5 minutes, phone the service.');
  });

  it('writes the invitation validity, the code validity and the re-verification period from the numbers', () => {
    expect(copy.invitationValid(POLICY_DEFAULTS)).toBe('Valid for 48 hours.');
    expect(copy.textCodeValid(POLICY_DEFAULTS)).toBe('The code works for 10 minutes.');
    expect(copy.reverifyEvery(POLICY_DEFAULTS)).toBe('You will be asked to confirm your number every 30 days.');
  });

  it('writes the pressure line from the level', () => {
    expect(copy.pressureHigh(POLICY_DEFAULTS)).toBe('5 or more services are limited or worse.');
    expect(copy.pressureHigh({ ...POLICY_DEFAULTS, pressureHighFrom: 7 })).toBe('7 or more services are limited or worse.');
  });
});

describe('the capacity heading (TEN-069, KI-545)', () => {
  it('is the organisation and the tenant’s own word for its system', () => {
    expect(copy.capacityHeading(A, 'Dorset')).toBe('Dorset Capacity A');
  });

  it('is the system word alone when the board names no organisation', () => {
    expect(copy.capacityHeading(A, null)).toBe('Capacity A');
  });

  it('is null for a tenant with no wording, or no profile: the page then keeps the product’s own words', () => {
    expect(copy.capacityHeading(C, 'Dorset')).toBeNull();
    expect(copy.capacityHeading(null, 'Dorset')).toBeNull();
  });

  it('prints the words as text', () => {
    expect(copy.capacityHeading({ ...A, wording: { ...A.wording!, systemName: '<b>X</b>' } }, 'Y')).toBe('Y <b>X</b>');
  });
});
