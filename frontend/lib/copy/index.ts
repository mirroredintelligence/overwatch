import type { TenantPolicy } from '@/lib/tenant/policy';
import type { TenantProfile } from '@/lib/tenant/profile';

// The words the pages print that depend on the tenant or on a policy number (TEN-049). They take the
// profile and the policy as arguments: no function here names a place, an organisation, a system or a
// phone number of its own, and none writes a policy number as a literal. Where a tenant has not set a
// word the sentence is left out (null) rather than invented (H-T15). The words are text: a page prints
// them with React, which escapes them, and never as markup.

export type Unit = 'minute' | 'hour' | 'day';

/** "1 minute", "10 minutes". The count is a positive whole number. */
export function duration(count: number, unit: Unit): string {
  if (!Number.isInteger(count) || count < 1) throw new Error('A duration is a positive whole number');
  return `${count} ${unit}${count === 1 ? '' : 's'}`;
}

export const copy = {
  /** The staff sign-in page. The product does not know what kind of organisation signs in. */
  signIn: () => ({
    intro: 'Use your staff account. There is no new password.',
    button: 'Sign in with your staff account',
  }),

  /** The line under the wall board's heading: the tenant's own coordination team name, or nothing. */
  wallSubtitle: (profile: TenantProfile | null): string | null => profile?.wording?.coordinationTeamName ?? null,

  /** "Phone <team> on <number>." with whichever the tenant has set; null when it has neither. */
  phoneTheCoordinationTeam: (profile: TenantProfile | null): string | null => {
    const team = profile?.wording?.coordinationTeamName ?? null;
    const phone = profile?.coordinationPhone ?? null;
    if (team !== null && phone !== null) return `Phone ${team} on ${phone}.`;
    if (team !== null) return `Phone ${team}.`;
    if (phone !== null) return `Phone ${phone}.`;
    return null;
  },

  bookingReplyBy: (policy: TenantPolicy) => `Reply within ${duration(policy.bookingReplyMinutes, 'minute')}.`,
  bookingPhonePrompt: (policy: TenantPolicy) =>
    `If there is no answer after ${duration(policy.bookingPhonePromptMinutes, 'minute')}, phone the service.`,
  invitationValid: (policy: TenantPolicy) => `Valid for ${duration(policy.invitationHours, 'hour')}.`,
  textCodeValid: (policy: TenantPolicy) => `The code works for ${duration(policy.textCodeMinutes, 'minute')}.`,
  reverifyEvery: (policy: TenantPolicy) =>
    `You will be asked to confirm your number every ${duration(policy.reverifyDays, 'day')}.`,
  pressureHigh: (policy: TenantPolicy) => `${policy.pressureHighFrom} or more services are limited or worse.`,
} as const;
