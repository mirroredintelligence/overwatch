// The criteria of a service as the browser reads them (W14), from the back end's criteria history
// (`GET /fhir/Basic`, routes_criteria.py `_view_basic`). Pure. An advisor is sent the current version
// only, with its status, review date, age range and the need codes it accepts and excludes; the author
// and the day of the change are not sent, so those stay null and the dialog says "not recorded". A
// need code the rules do not list is never guessed at: the text is null and the dialog says to phone.
import { NEEDS } from './codes';

export type CriteriaView = {
  accepts: string | null;
  excludes: string | null;
  version: number;
  reviewedOn: string | null;
  reviewBy: string;
  owner: string | null;
  overdue: boolean;
};

type Record_ = Record<string, unknown>;
const asRecord = (value: unknown): Record_ | null =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record_) : null;

/** The labels of a list of need codes, in the order sent; null when it is not a list or holds a code the rules do not list. */
function needLabels(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const labels: string[] = [];
  for (const code of value) {
    const need = NEEDS.find((item) => item.code === code);
    if (need === undefined) return null;
    labels.push(need.label);
  }
  return labels;
}

function ageText(min: unknown, max: unknown): string | null {
  if (typeof min !== 'number' || !Number.isInteger(min)) return null;
  return typeof max === 'number' && Number.isInteger(max) ? `Age ${min} to ${max}` : `Age ${min}+`;
}

/**
 * The current version of a service's criteria, or null when there is none. `today` is the London
 * calendar date (YYYY-MM-DD). Overdue is a review date before today.
 */
export function criteriaFromHistory(value: unknown, today: string): CriteriaView | null {
  const bundle = asRecord(value);
  if (bundle === null || bundle.resourceType !== 'Bundle' || !Array.isArray(bundle.entry)) return null;

  const current = bundle.entry
    .map((entry) => asRecord(asRecord(entry)?.resource))
    .find((resource) => resource?.resourceType === 'Basic' && resource.status === 'current');
  if (current === undefined || current === null) return null;

  const version = Number(asRecord(current.meta)?.versionId);
  const reviewBy = typeof current.reviewBy === 'string' ? current.reviewBy : null;
  if (!Number.isInteger(version) || reviewBy === null) return null;

  const accepts = needLabels(current.accepts);
  const age = ageText(current.ageMin, current.ageMax);
  const excludes = needLabels(current.excludes);
  return {
    accepts: accepts === null ? null : [...accepts, ...(age === null ? [] : [age])].join(' · '),
    excludes: excludes === null ? null : excludes.length === 0 ? 'None listed' : excludes.join(' · '),
    version,
    reviewedOn: null,
    reviewBy,
    owner: null,
    overdue: reviewBy < today,
  };
}
