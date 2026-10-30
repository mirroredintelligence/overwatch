// The BFF's registration shapes (W28, W29), as the browser reads them. The browser never
// sends or reads a tenant, an organisation id or a token: every field here is about one
// service or one registration in the session's own organisation (DEC-130, DEC-132).

export type ScopeFlag = 'in-pilot' | 'later' | 'out-of-scope';

/**
 * The registration state the scope list shows. `in-review` covers every state between submission
 * and approval (draft, submitted, needs-changes, approved, not live yet).
 */
export type ScopeRegistrationState =
  | 'not-invited'
  | 'invited'
  | 'in-review'
  | 'live'
  | 'paused'
  | 'not-approved'
  | 'reverify';

export type ScopeEntry = {
  serviceId: string;
  name: string;
  /** The category code (for example `urgent-community-response`); the page words it. */
  category: string;
  flag: ScopeFlag;
  registrationState: ScopeRegistrationState;
  reason?: string;
};

export type ScopeList = { entries: ScopeEntry[] };

export type QueueTab = 'to-review' | 'waiting' | 'go-live' | 'done';

export type QueueItem = {
  id: string;
  serviceName: string;
  state: string;
  /** ISO 8601 instant. */
  submittedAt: string;
  submittedByRole: string;
  firstIssue?: string;
};

export type QueueResponse = {
  counts: { toReview: number; waiting: number; goLive: number };
  items: QueueItem[];
};

export type AutomaticCheck = { key: string; label: string; ok: boolean; action?: string };

export type CallBackState = 'not-done' | 'done';
export type ScopeState = 'not-done' | 'done';
export type CriteriaState = 'not-done' | 'waiting' | 'done';

export type Overview = {
  id: string;
  serviceName: string;
  registeredBy: { name: string; role: string };
  automaticChecks: AutomaticCheck[];
  manualChecks: { callback: CallBackState; scope: ScopeState; criteria: CriteriaState };
  /** The call-back: the number from the register, the number the applicant gave, and the directory's name. */
  callBack?: CallBackDetails;
  /** The pathway's name, as tenant configuration words it (for example the area's urgent care pathway). */
  pathwayName?: string;
};

export type CallBackDetails = {
  /** The number from the NHS register or the directory. The only number the call-back may use. */
  numberToCall: string;
  /** The number on the registration. Shown for comparison; never called. */
  numberGiven?: string;
  /** The directory's name, from tenant configuration (for example "the area directory"). */
  directoryName?: string;
};

export type TimelineItem = { at: string; label: string };

export type Decision = {
  /** The labels of the checks still open, from the back-end approval gate. */
  missing: string[];
  approvedBy: string[];
  test: { sentAt?: string; answeredAt?: string };
  timeline: TimelineItem[];
};

export type CallBackResult = 'confirmed' | 'not-confirmed' | 'no-answer';

export type DecisionAction = 'approve' | 'send-back' | 'not-approve';

export type ScopeAnswer = 'yes' | 'no' | 'not-sure';

export type ScopeAnswers = {
  pathway: ScopeAnswer;
  spoaReferrals: ScopeAnswer;
  canReport: ScopeAnswer;
  categoryOnList: ScopeAnswer;
};
