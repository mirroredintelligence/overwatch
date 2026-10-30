// The criteria shapes the owner's pages read (W30, W31). Criteria are what advisors rely on, so every
// number and date here is the version's own, never one from another service or organisation.

export const NEED_CODES = [
  'fall-no-injury',
  'frailty',
  'wound-care',
  'iv-therapy',
  'palliative',
  'dementia',
  'suspected-fracture',
  'head-injury-anticoagulants',
  'infection-isolation',
] as const;

export type NeedCode = (typeof NEED_CODES)[number];

/** The values of one version of the criteria. `ageMax` null means no upper limit. */
export type CriteriaValues = {
  accepts: NeedCode[];
  excludes: NeedCode[];
  ageMin: number;
  ageMax: number | null;
  districts: string[];
};

export type CriteriaOverview = {
  serviceName: string;
  current: CriteriaValues & { version: number; reviewBy: string };
  /** A version waiting for the second approval. Advisors still see `current` until it is approved. */
  draft?: CriteriaValues & {
    version: number;
    reviewBy: string;
    status: 'waiting' | 'sent-back';
    sentAt?: string;
    note?: string;
  };
  /** The day the review date passed, when it has (W31). */
  overdueSince?: string;
};

export type ReviewPeriod = 3 | 6 | 12;
