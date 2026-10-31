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
/** Why a recorded score is changed (Q7): the back end's closed set, never free text. [ASSUMED] wording. */
export const SCORE_CORRECTION_REASONS = [
  { code: 'typing-error', label: 'I entered it wrongly' },
  { code: 'referrer-corrected', label: 'The referrer gave a corrected score' },
  { code: 'rescored', label: 'The patient was scored again' },
] as const;
export type ScoreCorrectionReasonCode = (typeof SCORE_CORRECTION_REASONS)[number]['code'];
export const isScoreCorrectionReason = (value: unknown): value is ScoreCorrectionReasonCode =>
  SCORE_CORRECTION_REASONS.some((reason) => reason.code === value);

export type CaseInput = {
  referrerType: ReferrerCode;
  ageBand: AgeCode;
  /** A full postcode, or null to leave the district the back end already holds as it is (DEC-398). */
  postcode: string | null;
  needs: NeedCode[];
  urgency: UrgencyCode;
  scores: Score[];
  /** Why a recorded score was changed. Sent only with a score that differs from the recorded one (Q7). */
  scoreCorrectionReason?: ScoreCorrectionReasonCode | null;
};

/** What the BFF answers for a case. Nulls mean not yet recorded. */
export type CaseView = {
  id: string;
  /** The four-digit case number the advisor reads out and the audit uses. Never part of an address (DEC-631). */
  reference: string | null;
  referrerType: ReferrerCode | null;
  ageBand: AgeCode | null;
  /** The postcode DISTRICT: the back end keeps no more of a postcode (DEC-398), and none once closed. */
  postcode: string | null;
  needs: NeedCode[];
  urgency: UrgencyCode | null;
  scores: Score[];
  /** How many times a recorded score was corrected: the first score and each reason are in the audit (Q7). */
  scoreCorrections: number;
  /** When the back end opened the case (ServiceRequest.authoredOn): the call clock counts from it. */
  openedAt: string | null;
  /** A closed case cannot change (D18): it has no postcode or needs, and the page says so. */
  closed: boolean;
  closedAt: string | null;
  outcome: string | null;
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
  // normalised form is what is saved. No postcode leaves the district on record as it is; a district
  // on its own is not a postcode and is refused.
  let postcode: string | null = null;
  if (source.postcode !== undefined && source.postcode !== null) {
    postcode = typeof source.postcode === 'string' ? normalisePostcode(source.postcode) : null;
    if (postcode === null) return null;
  }
  const scores = parseScores(source.scores);
  if (scores === null) return null;
  // A reason is one of the listed ones or absent; any other text is refused, not passed on.
  const reason = source.scoreCorrectionReason;
  if (reason !== undefined && reason !== null && !isScoreCorrectionReason(reason)) return null;
  return {
    referrerType: source.referrerType,
    ageBand: source.ageBand,
    postcode,
    needs: [...new Set(needs)],
    urgency: source.urgency,
    scores,
    scoreCorrectionReason: reason ?? null,
  };
}

