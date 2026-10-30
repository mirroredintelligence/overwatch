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
  /** The shift lead who can change the owner, as tenant configuration gives it (W31). */
  shiftLead?: { role: string; phone: string };
};

/** The version waiting for the second approval, as the approver reads it (W31). */
export type PendingChange = {
  serviceName: string;
  taskId: string;
  isAuthor: boolean;
  /** The change as words, or null when there is no earlier version (the registration case). */
  changes: string[] | null;
  /** The whole of the criteria, shown when there is no earlier version to compare. */
  full?: CriteriaValues & { version: number; reviewBy: string; ownerRole: string };
  reason: string;
  authorRole: string;
};

/** One line of the version history (W31). The back end gives the review date, not when a version was made. */
export type HistoryVersion = {
  version: number;
  status: 'waiting' | 'current' | 'replaced' | 'retired';
  reviewBy: string;
  criteriaId: string;
};

export type ReviewPeriod = 3 | 6 | 12;

/** The steps of the owner's flow. `status` is the tracker after a send, reached from the overview. */
export type CriteriaStep = 'overview' | 'confirm' | 'edit' | 'preview' | 'send';
