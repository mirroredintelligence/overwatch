import { describe, expect, it } from 'vitest';
import { ADVICE_CHOICES, adviceText, NOTE_LIMIT, validateAdvice } from './advice';

describe('validateAdvice', () => {
  it('requires an advice choice', () => {
    const result = validateAdvice({ reason: 'within-criteria-on-judgement' });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors).toContain('Choose what you advise.');
  });

  it('sends the back end\'s values: go-ahead with the reason within criteria on judgement', () => {
    expect(validateAdvice({ advice: 'go-ahead', reason: 'within-criteria-on-judgement' })).toEqual({
      ok: true,
      value: { advice: 'go-ahead', reason: 'within-criteria-on-judgement' },
    });
  });

  it('refuses a choice the back end does not offer', () => {
    expect(validateAdvice({ advice: 'maybe' }).ok).toBe(false);
  });

  it('blocks a note of 281 characters and says the limit', () => {
    const result = validateAdvice({ advice: 'go-ahead', note: 'x'.repeat(NOTE_LIMIT + 1) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors).toContain(`Keep the note to ${NOTE_LIMIT} characters`);
  });

  it('accepts a note of exactly 280 characters', () => {
    expect(validateAdvice({ advice: 'go-ahead', note: 'x'.repeat(NOTE_LIMIT) }).ok).toBe(true);
  });

  it('offers the four advice choices the back end takes', () => {
    expect(ADVICE_CHOICES).toEqual(['go-ahead', 'use-another-service', 'clinical-call-to-referrer', 'emergency-route']);
  });
});

describe('adviceText (KI-768)', () => {
  it('names the service on "Go ahead" when the request recorded one', () => {
    expect(adviceText('go-ahead', 'UCR West')).toBe('Go ahead with UCR West');
  });

  it('is the general label when no service is recorded, and for every other choice', () => {
    expect(adviceText('go-ahead', null)).toBe('Go ahead with the service');
    expect(adviceText('use-another-service', 'UCR West')).toBe('Use another service');
    expect(adviceText('emergency-route', 'UCR West')).toBe('Send to the emergency route under local protocol');
  });

  it('passes a choice it does not know through as it is', () => {
    expect(adviceText('something-new', 'UCR West')).toBe('something-new');
  });
});
