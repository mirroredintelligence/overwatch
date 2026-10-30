import { normalisePostcode } from './postcode';
import { parseScores, type Score } from './scores';

// The coded values of a case (W11). The browser sends and reads these codes; the labels are shown
// only. The codes are the back end's (domain/codes.py, docs/spec/contracts.md), so a label change
// never changes what is stored.

export const REFERRERS = [
  { code: 'ambulance-crew', label: 'Ambulance crew', id: 'AMBULANCE' },
  { code: 'care-home', label: 'Care home', id: 'CARE-HOME' },
  { code: 'gp', label: 'GP', id: 'GP' },
  { code: 'nhs-111', label: 'NHS 111', id: 'NHS-111' },
  { code: 'other', label: 'Other', id: 'OTHER' },
] as const;
export type ReferrerCode = (typeof REFERRERS)[number]['code'];

export const AGE_BANDS = [
  { code: '0-15', label: '0 to 15', id: '0-15' },
  { code: '16-64', label: '16 to 64', id: '16-64' },
  { code: '65-79', label: '65 to 79', id: '65-79' },
  { code: '80+', label: '80+', id: '80PLUS' },
] as const;
export type AgeCode = (typeof AGE_BANDS)[number]['code'];

// "more" needs sit behind the "More needs" control, so the first screen stays short.
export const NEEDS = [
  { code: 'fall-no-injury', label: 'Fall, no injury', short: 'Fall', id: 'FALL-NO-INJURY', more: false },
  { code: 'frailty', label: 'Frailty', short: 'Frailty', id: 'FRAILTY', more: false },
  { code: 'iv-therapy', label: 'IV therapy', short: 'IV therapy', id: 'IV-THERAPY', more: false },
  { code: 'wound-care', label: 'Wound care', short: 'Wound care', id: 'WOUND-CARE', more: false },
  { code: 'palliative', label: 'Palliative', short: 'Palliative', id: 'PALLIATIVE', more: false },
  { code: 'dementia', label: 'Dementia', short: 'Dementia', id: 'DEMENTIA', more: true },
  {
    code: 'suspected-fracture',
    label: 'Suspected fracture',
    short: 'Suspected fracture',
    id: 'SUSPECTED-FRACTURE',
    more: true,
  },
  {
    code: 'head-injury-anticoagulants',
    label: 'Head injury on anticoagulants',
    short: 'Head injury on anticoagulants',
    id: 'HEAD-INJURY-ANTICOAGULANTS',
    more: true,
  },
  {
    code: 'infection-isolation',
    label: 'Infection isolation',
    short: 'Infection isolation',
    id: 'INFECTION-ISOLATION',
    more: true,
  },
] as const;
export type NeedCode = (typeof NEEDS)[number]['code'];

export const URGENCIES = [
  { code: 'within-2-hrs', label: 'Within 2 hrs', id: 'WITHIN-2-HRS' },
  { code: 'today', label: 'Today', id: 'TODAY' },
  { code: 'planned', label: 'Planned', id: 'PLANNED' },
] as const;
export type UrgencyCode = (typeof URGENCIES)[number]['code'];

/** What the needs form saves. Nothing is typed except the postcode; every other field is a code. */
export type CaseInput = {
  referrerType: ReferrerCode;
  ageBand: AgeCode;
  postcode: string;
  needs: NeedCode[];
  urgency: UrgencyCode;
  scores: Score[];
};

/** What the BFF answers for a case. Nulls mean not yet recorded. */
export type CaseView = {
  id: string;
  referrerType: ReferrerCode | null;
  ageBand: AgeCode | null;
  postcode: string | null;
  needs: NeedCode[];
  urgency: UrgencyCode | null;
  scores: Score[];
  /** Not returned by the back end today (see docs/delivery/fragments/W11.md). Null. */
  openedAt: string | null;
  etag: string | null;
};

export function labelOf<T extends { code: string; label: string }>(
  list: readonly T[],
  code: string | null,
): string | null {
  return list.find((item) => item.code === code)?.label ?? null;
}

const isCode = <T extends string>(list: readonly { code: T }[], value: unknown): value is T =>
  typeof value === 'string' && list.some((item) => item.code === value);

export const isReferrerCode = (value: unknown): value is ReferrerCode => isCode(REFERRERS, value);
export const isAgeCode = (value: unknown): value is AgeCode => isCode(AGE_BANDS, value);
export const isNeedCode = (value: unknown): value is NeedCode => isCode(NEEDS, value);
export const isUrgencyCode = (value: unknown): value is UrgencyCode => isCode(URGENCIES, value);

/**
 * The strict read of a save (PUT): every field coded and in its list, and nothing else. Any other
 * key is dropped, so a name or a tenant the browser sends is never forwarded (W11, DEC-130).
 */
export function parseCaseInput(value: unknown): CaseInput | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  const needs = source.needs;
  if (!Array.isArray(needs) || needs.length === 0) return null;
  if (!needs.every(isNeedCode)) return null;
  if (!isReferrerCode(source.referrerType)) return null;
  if (!isAgeCode(source.ageBand)) return null;
  if (!isUrgencyCode(source.urgency)) return null;
  // The browser normalises a postcode too; the back end's rule is applied here as well, and the
  // normalised form is what is saved.
  const postcode = typeof source.postcode === 'string' ? normalisePostcode(source.postcode) : null;
  if (postcode === null) return null;
  const scores = parseScores(source.scores);
  if (scores === null) return null;
  return {
    referrerType: source.referrerType,
    ageBand: source.ageBand,
    postcode,
    needs: [...new Set(needs)],
    urgency: source.urgency,
    scores,
  };
}

