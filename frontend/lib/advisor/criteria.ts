// The criteria of a service as the browser reads them (W14), from the back end's criteria history
// (`GET /fhir/Basic`). Pure. The history answer carries a version, a status and a review date; the
// text of what a service accepts and excludes is not in it yet, so those fields are null and the
// dialog says so rather than show a guess (docs/delivery/fragments/W14.md).

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

  return {
    accepts: null,
    excludes: null,
    version,
    reviewedOn: null,
    reviewBy,
    owner: null,
    overdue: reviewBy < today,
  };
}
