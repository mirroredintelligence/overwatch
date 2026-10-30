import { describe, expect, it } from 'vitest';
import { POLICY_DEFAULTS, parsePolicy, policyFor } from './policy';
import { parseProfile } from './profile';

// The numbers the copy prints (a booking is asked for within 10 minutes, a text code lasts 10
// minutes...). They are parameters of the copy, never literals in it, because a tenant may set some of
// them within safe bounds (DEC-134 item 14, the back end's TenantPolicy). Their defaults are the back
// end's defaults and the domain rules'. Until the back end publishes a tenant's policy to staff, every
// tenant has the defaults.

describe('POLICY_DEFAULTS', () => {
  it('equals the back end defaults and the domain rules', () => {
    expect(POLICY_DEFAULTS).toEqual({
      replyWindowMinutes: 30,
      staleWarningHours: 2,
      pressureWatchFrom: 3,
      pressureHighFrom: 5,
      correctionWindowMinutes: 15,
      maxServicesPerPhone: 3,
      bookingReplyMinutes: 10,
      bookingPhonePromptMinutes: 5,
      withdrawalEscalateMinutes: 10,
      clinicalTakeMinutes: 10,
      reverifyDays: 30,
      notUpdatedAlertHours: 2,
      invitationHours: 48,
      textCodeMinutes: 10,
      wrongTries: 5,
      suppressUnder: 10,
    });
  });

  it('is frozen', () => {
    expect(Object.isFrozen(POLICY_DEFAULTS)).toBe(true);
  });
});

describe('policyFor', () => {
  const profile = parseProfile({ displayName: 'Sample Area A', timeZone: 'Europe/London', locale: 'en-GB', wording: null, coordinationPhone: null });

  it('is the defaults, for a profile and for no profile', () => {
    expect(policyFor(profile)).toEqual(POLICY_DEFAULTS);
    expect(policyFor(null)).toEqual(POLICY_DEFAULTS);
  });

  it('is a new frozen object each time, so no caller can change what another sees', () => {
    const one = policyFor(profile);
    const two = policyFor(profile);
    expect(one).not.toBe(two);
    expect(Object.isFrozen(one)).toBe(true);
    expect(() => {
      (one as { wrongTries: number }).wrongTries = 99;
    }).toThrow();
    expect(two.wrongTries).toBe(5);
  });
});

describe('parsePolicy', () => {
  it('takes the fields it is given and the defaults for the rest', () => {
    expect(parsePolicy({ bookingReplyMinutes: 15, clinicalTakeMinutes: 12 })).toEqual({
      ...POLICY_DEFAULTS,
      bookingReplyMinutes: 15,
      clinicalTakeMinutes: 12,
    });
  });

  it('never takes a platform constant from the answer: the invitation, text code and wrong-tries values are fixed', () => {
    const parsed = parsePolicy({ invitationHours: 1, textCodeMinutes: 1, wrongTries: 1, suppressUnder: 1 });
    expect(parsed.invitationHours).toBe(48);
    expect(parsed.textCodeMinutes).toBe(10);
    expect(parsed.wrongTries).toBe(5);
    expect(parsed.suppressUnder).toBe(10);
  });

  it.each([
    ['not a number', { bookingReplyMinutes: '15' }],
    ['not a whole number', { bookingReplyMinutes: 7.5 }],
    ['zero', { bookingReplyMinutes: 0 }],
    ['negative', { bookingReplyMinutes: -5 }],
    ['not finite', { bookingReplyMinutes: Number.POSITIVE_INFINITY }],
    ['absurdly large', { bookingReplyMinutes: 100000 }],
  ])('uses the default for a field that is %s', (_name, body) => {
    expect(parsePolicy(body).bookingReplyMinutes).toBe(10);
  });

  it('is the defaults for anything that is not an object, and ignores unknown fields', () => {
    for (const value of [null, undefined, 'x', 3, []]) expect(parsePolicy(value)).toEqual(POLICY_DEFAULTS);
    expect(Object.keys(parsePolicy({ tenant: 'x', extra: 1 })).sort()).toEqual(Object.keys(POLICY_DEFAULTS).sort());
  });

  it('keeps the pressure levels in order: a watch level at or above the high level is refused and both go back to the defaults', () => {
    expect(parsePolicy({ pressureWatchFrom: 6, pressureHighFrom: 5 })).toMatchObject({ pressureWatchFrom: 3, pressureHighFrom: 5 });
    expect(parsePolicy({ pressureWatchFrom: 2, pressureHighFrom: 6 })).toMatchObject({ pressureWatchFrom: 2, pressureHighFrom: 6 });
  });

  it('keeps the booking prompt before the booking reply window', () => {
    expect(parsePolicy({ bookingPhonePromptMinutes: 12, bookingReplyMinutes: 10 })).toMatchObject({ bookingPhonePromptMinutes: 5, bookingReplyMinutes: 10 });
  });
});
