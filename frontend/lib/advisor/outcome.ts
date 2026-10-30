// The outcome of a call (W15): the codes the back end records (domain/codes.py `Outcome` and
// `BestFitNotUsedReason`), the labels the form shows, and the one strict read of a save.

export const OUTCOMES = [
  { code: 'accepted-and-booked', label: 'Accepted and booked', id: 'ACCEPTED' },
  { code: 'declined', label: 'Declined', id: 'DECLINED' },
  { code: 'redirected', label: 'Redirected', id: 'REDIRECTED' },
  { code: 'caller-cancelled', label: 'Caller cancelled', id: 'CANCELLED' },
] as const;
export type OutcomeCode = (typeof OUTCOMES)[number]['code'];

/** The outcomes that come from the address (`?outcome=`) and are shown as text, not as a chip. */
export const TEXT_OUTCOMES = {
  'no-service-fits': 'No service fits',
  'out-of-area': 'Out of area', // [ASSUMED] the words for the out-of-area outcome; the spec gives none.
} as const;
export type TextOutcome = keyof typeof TEXT_OUTCOMES;

export const BEST_FIT_REASONS = [
  { code: 'full', label: 'Full', id: 'FULL' },
  { code: 'declined', label: 'Declined', id: 'DECLINED' },
  { code: 'data-too-old', label: 'Data too old', id: 'DATA-TOO-OLD' },
  { code: 'caller-preference', label: 'Caller preference', id: 'CALLER-PREFERENCE' },
  { code: 'clinical-override', label: 'Clinical override', id: 'CLINICAL-OVERRIDE' },
] as const;
export type BestFitCode = (typeof BEST_FIT_REASONS)[number]['code'];

export type OutcomeInput = {
  outcome: OutcomeCode | TextOutcome;
  bestFitNotUsed?: BestFitCode;
  destinationServiceId?: string;
};

const SERVICE_ID = /^[A-Za-z0-9_-]{1,64}$/;

export function isTextOutcome(value: unknown): value is TextOutcome {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(TEXT_OUTCOMES, value);
}

/** The outcome named in an address, when it is one the finish screen takes; otherwise null. */
export function outcomeFromAddress(value: unknown): TextOutcome | null {
  return isTextOutcome(value) ? value : null;
}

/**
 * The strict read of a save. The outcome and the reason are codes on their lists; a destination, when
 * given, is a service id. Anything else is refused, so nothing outside the lists is recorded.
 */
export function parseOutcomeInput(value: unknown): OutcomeInput | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  const outcome = source.outcome;
  const allowed = [...OUTCOMES.map((item) => item.code), ...Object.keys(TEXT_OUTCOMES)] as string[];
  if (typeof outcome !== 'string' || !allowed.includes(outcome)) return null;

  const input: OutcomeInput = { outcome: outcome as OutcomeInput['outcome'] };
  if (source.bestFitNotUsed !== undefined) {
    const reason = BEST_FIT_REASONS.find((item) => item.code === source.bestFitNotUsed);
    if (reason === undefined) return null;
    input.bestFitNotUsed = reason.code;
  }
  if (source.destinationServiceId !== undefined) {
    if (typeof source.destinationServiceId !== 'string' || !SERVICE_ID.test(source.destinationServiceId)) return null;
    input.destinationServiceId = source.destinationServiceId;
  }
  return input;
}
