// The clinical advice choices, reasons and the note's limit (W44; domain/use_cases clinical_advice.py).
// The values are the back end's. Where the prompt named a reason the back end does not take
// ("within-criteria"), the back end's value is used (DEC-718).

export const REQUEST_URGENCIES = ['now', 'within-15-min'] as const;
export const REQUEST_WHYS = ['borderline-criteria', 'unsure-of-urgency', 'other'] as const;
export const ADVICE_CHOICES = ['go-ahead', 'use-another-service', 'clinical-call-to-referrer', 'emergency-route'] as const;
export const ADVICE_REASONS = ['within-criteria-on-judgement', 'safer-alternative', 'other'] as const;
export const NOTE_LIMIT = 280;

export const ADVICE_LABELS: Readonly<Record<(typeof ADVICE_CHOICES)[number], string>> = {
  'go-ahead': 'Go ahead with the service',
  'use-another-service': 'Use another service',
  'clinical-call-to-referrer': 'Needs a clinical call to the referrer',
  'emergency-route': 'Send to the emergency route under local protocol',
};

/**
 * The advice as a sentence. "Go ahead" names the service the request recorded (KI-768): advice about one
 * service is read as about that one. With none recorded, or for any other choice, it is the general label.
 */
export function adviceText(choice: string, serviceName: string | null): string {
  if (choice === 'go-ahead' && serviceName !== null) return `Go ahead with ${serviceName}`;
  return choice in ADVICE_LABELS ? ADVICE_LABELS[choice as keyof typeof ADVICE_LABELS] : choice;
}

export const REASON_LABELS: Readonly<Record<(typeof ADVICE_REASONS)[number], string>> = {
  'within-criteria-on-judgement': 'Within criteria on my judgement',
  'safer-alternative': 'Safer alternative',
  other: 'Other',
};

export type Advice = { advice: (typeof ADVICE_CHOICES)[number]; reason?: (typeof ADVICE_REASONS)[number]; note?: string };
export type AdviceCheck = { ok: true; value: Advice } | { ok: false; errors: string[] };

/** The advice as the back end takes it. Every refusal is a plain sentence the screen can show. */
export function validateAdvice(input: unknown): AdviceCheck {
  const source = (typeof input === 'object' && input !== null ? input : {}) as Record<string, unknown>;
  const errors: string[] = [];
  const advice = source.advice;
  const choice = typeof advice === 'string' && (ADVICE_CHOICES as readonly string[]).includes(advice);
  if (!choice) errors.push('Choose what you advise.');
  const reason = source.reason;
  const hasReason = typeof reason === 'string' && reason !== '';
  if (hasReason && !(ADVICE_REASONS as readonly string[]).includes(reason)) errors.push('Choose a reason from the list.');
  const note = typeof source.note === 'string' ? source.note : '';
  if (note.length > NOTE_LIMIT) errors.push(`Keep the note to ${NOTE_LIMIT} characters`);
  if (errors.length > 0) return { ok: false, errors };
  const value: Advice = { advice: advice as Advice['advice'] };
  if (hasReason) value.reason = reason as Advice['reason'];
  if (note.trim() !== '') value.note = note.trim();
  return { ok: true, value };
}
