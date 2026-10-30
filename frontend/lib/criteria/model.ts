// The owner's criteria rules and parsers (W30, W31). Pure: no I/O. The wording of each rule is the
// one ui-screens.md gives (CriteriaOwner screens 2 to 7).
import type { CriteriaOverview, CriteriaValues, NeedCode, ReviewPeriod } from './types';
import { NEED_CODES } from './types';

export const NEED_LABELS: Readonly<Record<NeedCode, string>> = {
  'fall-no-injury': 'Fall, no injury',
  frailty: 'Frailty',
  'wound-care': 'Wound care',
  'iv-therapy': 'IV therapy',
  palliative: 'Palliative',
  dementia: 'Dementia',
  'suspected-fracture': 'Suspected fracture',
  'head-injury-anticoagulants': 'Head injury on anticoagulants',
  'infection-isolation': 'Infection isolation',
};

/** The exclusion list says "Needs IV therapy" (ui-screens), the acceptance list says "IV therapy". */
const EXCLUDE_LABEL_OVERRIDES: Partial<Record<NeedCode, string>> = { 'iv-therapy': 'Needs IV therapy' };

export const ACCEPT_CHOICES: readonly NeedCode[] = ['fall-no-injury', 'frailty', 'wound-care', 'iv-therapy', 'palliative', 'dementia'];

/**
 * The exclusion chips in order: the four the artboard names, then "No exclusions", then the other
 * needs. Every need can be excluded, so the conflict rule can be reached for any need (DEC-701).
 */
export const EXCLUDE_CHOICES: readonly NeedCode[] = [
  'suspected-fracture',
  'head-injury-anticoagulants',
  'iv-therapy',
  'infection-isolation',
  'fall-no-injury',
  'frailty',
  'wound-care',
  'palliative',
  'dementia',
];

export const REVIEW_PERIODS: readonly ReviewPeriod[] = [3, 6, 12];
export const REASON_MAX_LENGTH = 200;
export const AGE_MIN_LIMIT = 0;
export const AGE_MAX_LIMIT = 120;
const DISTRICT_SHAPE = /^[A-Z]{1,2}[0-9][A-Z0-9]?$/;

export function excludeLabel(need: NeedCode): string {
  return EXCLUDE_LABEL_OVERRIDES[need] ?? NEED_LABELS[need];
}

export function isNeedCode(value: unknown): value is NeedCode {
  return typeof value === 'string' && (NEED_CODES as readonly string[]).includes(value);
}

/** A need cannot be both accepted and not accepted (W30 test 3). */
export function conflictError(accepts: readonly NeedCode[], excludes: readonly NeedCode[]): string | null {
  return accepts.some((need) => excludes.includes(need)) ? 'A need cannot be both accepted and not accepted' : null;
}

export function reviewPeriodError(months: ReviewPeriod | null): string | null {
  return months === null ? 'Choose when to review again' : null;
}

export function reasonError(reason: string): string | null {
  const trimmed = reason.trim();
  if (trimmed === '') return 'Enter why you are changing this';
  return trimmed.length > REASON_MAX_LENGTH ? `Keep the reason to ${REASON_MAX_LENGTH} characters` : null;
}

export function districtShape(district: string): boolean {
  return DISTRICT_SHAPE.test(district);
}

/** The oldest-age rule: no limit, or a whole number at least the youngest age. */
export function ageError(ageMin: number, ageMax: number | null): string | null {
  if (!Number.isInteger(ageMin) || ageMin < AGE_MIN_LIMIT || ageMin > AGE_MAX_LIMIT) return 'Enter the youngest age';
  if (ageMax !== null && (!Number.isInteger(ageMax) || ageMax < ageMin || ageMax > AGE_MAX_LIMIT)) {
    return 'The oldest age must be at least the youngest age';
  }
  return null;
}

/** The plain words for what advisors see: "Accepts: Fall, no injury, Frailty, age 18+". */
export function acceptsLine(values: CriteriaValues): string {
  const needs = values.accepts.map((need) => NEED_LABELS[need]);
  const age = values.ageMax === null ? `age ${values.ageMin}+` : `age ${values.ageMin} to ${values.ageMax}`;
  return `Accepts: ${[...needs, age].join(', ')}`;
}

export function doesNotAcceptLine(values: CriteriaValues): string {
  const needs = values.excludes.map((need) => excludeLabel(need));
  return needs.length === 0 ? 'Does not accept: nothing listed' : `Does not accept: ${needs.join(', ')}`;
}

export function districtsLine(values: CriteriaValues): string {
  return `Postcode districts: ${values.districts.join(', ')}`;
}

/** The criteria as a set of named values, so two versions can be compared field by field. */
export function valuesOf(overview: CriteriaOverview['current']): CriteriaValues {
  return {
    accepts: [...overview.accepts],
    excludes: [...overview.excludes],
    ageMin: overview.ageMin,
    ageMax: overview.ageMax,
    districts: [...overview.districts],
  };
}

/** A date in the page's words: "12 Dec". Months are named here, so the wording never depends on the browser. */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const;

export function shortDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (match === null) return iso;
  const month = Number(match[2]);
  return `${Number(match[3])} ${MONTHS[month - 1] ?? ''}`.trim();
}

// ------------------------------------------------------------------------------- parsers

type Json = Record<string, unknown>;

function record(value: unknown): Json {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('expected an object');
  return value as Json;
}

function str(value: unknown): string {
  if (typeof value !== 'string') throw new Error('expected a string');
  return value;
}

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) throw new Error('expected a list');
  return value.map(str);
}

function needs(value: unknown): NeedCode[] {
  if (!Array.isArray(value) || !value.every(isNeedCode)) throw new Error('unexpected need');
  return value as NeedCode[];
}

function whole(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value)) throw new Error('expected a whole number');
  return value;
}

function valuesFrom(value: unknown): CriteriaValues {
  const body = record(value);
  return {
    accepts: needs(body.accepts),
    excludes: needs(body.excludes),
    ageMin: whole(body.ageMin),
    ageMax: body.ageMax === null || body.ageMax === undefined ? null : whole(body.ageMax),
    districts: strings(body.districts),
  };
}

export function parseCriteriaOverview(value: unknown): CriteriaOverview {
  const body = record(value);
  const current = record(body.current);
  const overdueSince = body.overdueSince === undefined || body.overdueSince === null ? undefined : str(body.overdueSince);
  let draft: CriteriaOverview['draft'];
  if (body.draft !== undefined && body.draft !== null) {
    const d = record(body.draft);
    const status = d.status;
    if (status !== 'waiting' && status !== 'sent-back') throw new Error('unexpected status');
    const note = d.note === undefined || d.note === null ? undefined : str(d.note);
    const sentAt = d.sentAt === undefined || d.sentAt === null ? undefined : str(d.sentAt);
    draft = {
      ...valuesFrom(d),
      version: whole(d.version),
      reviewBy: str(d.reviewBy),
      status,
      ...(sentAt !== undefined ? { sentAt } : {}),
      ...(note !== undefined ? { note } : {}),
    };
  }
  return {
    serviceName: str(body.serviceName),
    current: { ...valuesFrom(current), version: whole(current.version), reviewBy: str(current.reviewBy) },
    ...(draft !== undefined ? { draft } : {}),
    ...(overdueSince !== undefined ? { overdueSince } : {}),
  };
}
