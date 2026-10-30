import type { TenantProfile } from './profile';

// The numbers the copy prints (a booking reply within 10 minutes, a text code that lasts 10 minutes,
// "5 or more services"). Copy takes them as parameters and never writes one as a literal, because a
// tenant may set some of them within safe bounds (DEC-134 item 14: the back end's TenantPolicy, whose
// defaults these are, and domain-rules). Four are fixed for the platform and never read from an answer.
//
// Until the back end publishes a tenant's policy to its staff (it is read by the tenant administrator
// only, `routes_admin`), every tenant has the defaults; `policyFor` takes the profile so the
// tenant's own values can come with it without a change to a caller, and `parsePolicy` is ready for
// the route.

export type TenantPolicy = {
  /** A prompt's reply-by is due plus this. */
  readonly replyWindowMinutes: number;
  readonly staleWarningHours: number;
  readonly pressureWatchFrom: number;
  readonly pressureHighFrom: number;
  readonly correctionWindowMinutes: number;
  readonly maxServicesPerPhone: number;
  readonly bookingReplyMinutes: number;
  readonly bookingPhonePromptMinutes: number;
  readonly withdrawalEscalateMinutes: number;
  readonly clinicalTakeMinutes: number;
  readonly reverifyDays: number;
  readonly notUpdatedAlertHours: number;
  // Fixed for the platform:
  readonly invitationHours: number;
  readonly textCodeMinutes: number;
  readonly wrongTries: number;
  readonly suppressUnder: number;
};

export const POLICY_DEFAULTS: TenantPolicy = Object.freeze({
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

type Settable = Exclude<keyof TenantPolicy, 'invitationHours' | 'textCodeMinutes' | 'wrongTries' | 'suppressUnder'>;

// The largest value a field may take: a tenant's setting is bounded, and a value outside is the default.
const MAX: Record<Settable, number> = {
  replyWindowMinutes: 24 * 60,
  staleWarningHours: 24,
  pressureWatchFrom: 50,
  pressureHighFrom: 50,
  correctionWindowMinutes: 24 * 60,
  maxServicesPerPhone: 50,
  bookingReplyMinutes: 24 * 60,
  bookingPhonePromptMinutes: 24 * 60,
  withdrawalEscalateMinutes: 24 * 60,
  clinicalTakeMinutes: 24 * 60,
  reverifyDays: 366,
  notUpdatedAlertHours: 24,
};

const SETTABLE = Object.keys(MAX) as Settable[];

/** The policy for a tenant: today the defaults, as a new frozen object each time. */
export function policyFor(profile: TenantProfile | null): TenantPolicy {
  void profile;
  return Object.freeze({ ...POLICY_DEFAULTS });
}

/** The policy from an answer: the settable fields it holds that are whole numbers in bounds, the defaults for the rest. */
export function parsePolicy(body: unknown): TenantPolicy {
  const source = typeof body === 'object' && body !== null && !Array.isArray(body) ? (body as Record<string, unknown>) : {};
  const next: Record<string, number> = { ...POLICY_DEFAULTS };
  for (const field of SETTABLE) {
    const value = source[field];
    if (typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= MAX[field]) next[field] = value;
  }
  // The levels and timers must keep their order; a pair that does not goes back to the defaults together.
  if (next.pressureWatchFrom! >= next.pressureHighFrom!) {
    next.pressureWatchFrom = POLICY_DEFAULTS.pressureWatchFrom;
    next.pressureHighFrom = POLICY_DEFAULTS.pressureHighFrom;
  }
  if (next.bookingPhonePromptMinutes! >= next.bookingReplyMinutes!) {
    next.bookingPhonePromptMinutes = POLICY_DEFAULTS.bookingPhonePromptMinutes;
    next.bookingReplyMinutes = POLICY_DEFAULTS.bookingReplyMinutes;
  }
  return Object.freeze(next) as TenantPolicy;
}
