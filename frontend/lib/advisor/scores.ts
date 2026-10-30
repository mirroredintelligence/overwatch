// The referrer's scores (W12): what a referrer already measured, recorded exactly as given. Nothing
// here calculates, infers or checks a score beyond its allowed range (W12 done-when).

export const ACUITY_METHODS = ['pathways-dx', 'ambulance-category', 'manchester', 'news2', 'cfs'] as const;
export type AcuityMethod = (typeof ACUITY_METHODS)[number];

export const MANCHESTER_TRIAGE = [
  { code: 'immediate', label: 'Immediate' },
  { code: 'very-urgent', label: 'Very urgent' },
  { code: 'urgent', label: 'Urgent' },
  { code: 'standard', label: 'Standard' },
  { code: 'non-urgent', label: 'Non-urgent' },
] as const;
export type ManchesterCode = (typeof MANCHESTER_TRIAGE)[number]['code'];

export const AMBULANCE_CATEGORIES = [
  { value: 1, label: 'Category 1', hint: 'Life-threatening' },
  { value: 2, label: 'Category 2', hint: 'Emergency' },
  { value: 3, label: 'Category 3', hint: 'Urgent' },
  { value: 4, label: 'Category 4', hint: 'Less urgent' },
] as const;
export const AMBULANCE_MAX = 4;

export const NEWS2_MAX = 20;
export const CFS_MIN = 1;
export const CFS_MAX = 9;

/** The nine labels of the Clinical Frailty Scale, as the referrer names them. */
export const CFS_LABELS: Readonly<Record<number, string>> = {
  1: 'Very fit',
  2: 'Well',
  3: 'Managing well',
  4: 'Vulnerable',
  5: 'Mildly frail',
  6: 'Moderately frail',
  7: 'Severely frail',
  8: 'Very severely frail',
  9: 'Terminally ill',
};

export const PATHWAYS_MIN_CHARACTERS = 2;
export const PATHWAYS_DEBOUNCE_MS = 250;
export const PATHWAYS_RESULTS_MAX = 20;
/** A Pathways Dx code as the lookup returns it: letters, digits, dot, dash, underscore. */
export const PATHWAYS_CODE = /^[A-Za-z0-9._-]{1,32}$/;

export type Score =
  | { method: 'news2'; value: number }
  | { method: 'cfs'; value: number }
  | { method: 'ambulance-category'; value: number }
  | { method: 'manchester'; value: ManchesterCode }
  | { method: 'pathways-dx'; value: string };

const NEWS2_TEXT = /^\d{1,2}$/;

/**
 * What the NEWS2 box holds. Empty is no score (valid, null). Only whole numbers 0 to 20 are a score;
 * anything else is invalid and must not be recorded.
 */
export function parseNews2(text: string): { valid: true; value: number | null } | { valid: false } {
  if (text === '') return { valid: true, value: null };
  if (!NEWS2_TEXT.test(text)) return { valid: false };
  const value = Number(text);
  return value <= NEWS2_MAX ? { valid: true, value } : { valid: false };
}

const isWhole = (value: unknown, min: number, max: number): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;

function scoreOf(method: unknown, value: unknown): Score | null {
  switch (method) {
    case 'news2':
      return isWhole(value, 0, NEWS2_MAX) ? { method, value } : null;
    case 'cfs':
      return isWhole(value, CFS_MIN, CFS_MAX) ? { method, value } : null;
    case 'ambulance-category':
      return isWhole(value, 1, AMBULANCE_MAX) ? { method, value } : null;
    case 'manchester':
      return MANCHESTER_TRIAGE.some((item) => item.code === value) ? { method, value: value as ManchesterCode } : null;
    case 'pathways-dx':
      return typeof value === 'string' && PATHWAYS_CODE.test(value) ? { method, value } : null;
    default:
      return null;
  }
}

/**
 * The strict read of a list of scores: each method at most once, each value in its range or on its
 * list. Null for anything else, so nothing outside the rules is recorded.
 */
export function parseScores(value: unknown): Score[] | null {
  if (!Array.isArray(value)) return null;
  const seen = new Set<string>();
  const scores: Score[] = [];
  for (const item of value) {
    if (typeof item !== 'object' || item === null) return null;
    const { method, value: score } = item as { method?: unknown; value?: unknown };
    const parsed = scoreOf(method, score);
    if (parsed === null || seen.has(parsed.method)) return null;
    seen.add(parsed.method);
    scores.push(parsed);
  }
  return scores;
}
