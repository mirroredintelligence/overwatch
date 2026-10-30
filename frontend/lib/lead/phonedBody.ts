import { invalidRequest } from './bffInput';

// What the shift lead enters for "I phoned" with no case (W17, W42, W43): what the service said by phone and
// how many it can take (DEC-920). It mirrors the advisor's phoned answer (W14): "not accepting" carries no
// figure, and accepting and limited carry a whole number from 0 to 9999 ([ASSUMED], the same bound as W14).

export const SAID = ['accepting', 'limited', 'not-accepting'] as const;
export type Said = (typeof SAID)[number];
export const MAX_FIGURE = 9999;

export type PhonedInput = { said: Said; value?: number };

const KEYS = ['said', 'value'];

export function readPhonedBody(value: unknown): PhonedInput {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw invalidRequest();
  const body = value as Record<string, unknown>;
  if (Object.keys(body).some((key) => !KEYS.includes(key))) throw invalidRequest();
  const said = body.said;
  if (typeof said !== 'string' || !(SAID as readonly string[]).includes(said)) throw invalidRequest();
  if (said === 'not-accepting') {
    if (body.value !== undefined) throw invalidRequest();
    return { said: 'not-accepting' };
  }
  const figure = body.value;
  if (typeof figure !== 'number' || !Number.isInteger(figure) || figure < 0 || figure > MAX_FIGURE) throw invalidRequest();
  return { said: said as Said, value: figure };
}

/** The back end's body for the answer: "told" and, for a figure, "value" (routes_lead_views.py). */
export function phonedPayload(input: PhonedInput): { told: Said; value?: number } {
  return input.said === 'not-accepting' ? { told: input.said } : { told: input.said, value: input.value };
}
