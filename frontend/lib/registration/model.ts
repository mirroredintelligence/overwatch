// Pure rules and parsers for the registration pages (W28, W29). No I/O: the components and the
// BFF call these, so the wording and the gates are decided in one place.
import { londonTime } from '@/lib/board/format';
import type {
  CallBackResult,
  Decision,
  DecisionAction,
  Overview,
  QueueItem,
  QueueResponse,
  QueueTab,
  ScopeAnswer,
  ScopeAnswers,
  ScopeEntry,
  ScopeFlag,
  ScopeList,
  ScopeRegistrationState,
} from './types';

export const SCOPE_FLAGS: readonly ScopeFlag[] = ['in-pilot', 'later', 'out-of-scope'];
export const QUEUE_TABS: readonly QueueTab[] = ['waiting', 'sent-back', 'approved', 'live', 'not-approved'];
export const NOTE_MAX_LENGTH = 280;
export const NAME_MAX_LENGTH = 200;

const CATEGORY_LABELS: Readonly<Record<string, string>> = {
  'urgent-community-response': 'Urgent community response',
  'same-day-emergency-care': 'Same day emergency care',
  'inpatient-beds': 'Inpatient beds',
  'hospital-at-home-or-virtual-ward': 'Hospital at home or virtual ward',
  reablement: 'Reablement',
  'urgent-treatment': 'Urgent treatment',
  'mental-health-crisis': 'Mental health crisis',
  other: 'Other',
};

/** Every category a service may be given, in the order the lists show them. */
export const CATEGORY_CODES: readonly string[] = Object.keys(CATEGORY_LABELS);

/** The words for a category code. An unknown code is sentence-cased, never shown as it came. */
export function categoryLabel(code: string): string {
  const known = CATEGORY_LABELS[code];
  if (known !== undefined) return known;
  const words = code.replace(/[-_]+/g, ' ').trim().toLowerCase();
  return words.length === 0 ? 'Other' : words.charAt(0).toUpperCase() + words.slice(1);
}

const FLAG_LABELS: Readonly<Record<ScopeFlag, string>> = {
  'in-pilot': 'In pilot',
  later: 'Later',
  'out-of-scope': 'Out of scope',
};

export function flagLabel(flag: ScopeFlag): string {
  return FLAG_LABELS[flag];
}

const STATE_LABELS: Readonly<Record<ScopeRegistrationState, string>> = {
  'not-invited': 'Not invited',
  invited: 'Invited',
  'in-review': 'In review',
  live: 'Live',
  paused: 'Paused',
  'not-approved': 'Not approved',
  reverify: 'Re-verify due',
};

export function stateLabel(state: ScopeRegistrationState): string {
  return STATE_LABELS[state];
}

/** The queue's state words. A state the page does not know is shown as the back end's code. */
const QUEUE_STATE_LABELS: Readonly<Record<string, string>> = {
  submitted: 'Submitted',
  'in-review': 'In review',
  'needs-changes': 'Needs changes',
  approved: 'Approved, not live',
  live: 'Live',
  'not-approved': 'Not approved',
};

export function queueStateLabel(state: string): string {
  return QUEUE_STATE_LABELS[state] ?? state;
}

/** An invitation is offered only for a service in the pilot that has not been invited. */
export function canInvite(entry: ScopeEntry): boolean {
  return entry.flag === 'in-pilot' && entry.registrationState === 'not-invited';
}

/** The reason is needed for every flag but the pilot (W28, ui-screens ApprovalWeb1). */
export function reasonRequired(flag: ScopeFlag): boolean {
  return flag !== 'in-pilot';
}

export function scopeReasonError(flag: ScopeFlag, reason: string): string | null {
  return reasonRequired(flag) && reason.trim() === '' ? 'Enter a reason' : null;
}

export function queueTabLabel(tab: QueueTab, counts: QueueResponse['counts'] | null): string {
  const count = counts?.[tab];
  const words: Record<QueueTab, string> = {
    waiting: 'Waiting',
    'sent-back': 'Sent back',
    approved: 'Approved',
    live: 'Live',
    'not-approved': 'Not approved',
  };
  return count === undefined ? words[tab] : `${words[tab]} (${count})`;
}

export function submittedText(item: QueueItem): string {
  return `Submitted ${londonTime(item.submittedAt)} by ${item.submittedByRole}`;
}

// ------------------------------------------------------------------------- W29 check rules

export const CALLBACK_RESULTS: readonly CallBackResult[] = ['confirmed', 'not-confirmed', 'no-answer'];
export const SCOPE_ANSWERS: readonly ScopeAnswer[] = ['yes', 'no', 'not-sure'];

/** A confirmed call names who was spoken to (ui-screens ApprovalWeb1 screen 4). Other results need no role. */
export function callbackFormError(result: CallBackResult, spokeToRole: string): string | null {
  return result === 'confirmed' && spokeToRole.trim() === '' ? 'Enter who you spoke to' : null;
}

/** The message the back end gives when approval is refused, with the checks still missing. */
export function missingText(missing: readonly string[]): string {
  return `Approve is unavailable until: ${missing.join(', ')}`;
}

/** Approve is available only when the back end lists nothing missing. The list is never worked out here. */
export function canApprove(missing: readonly string[]): boolean {
  return missing.length === 0;
}

/** A send back and a refusal to approve need a note to the applicant; approval needs none. */
export function decisionNoteError(action: DecisionAction, note: string): string | null {
  const needsNote = action === 'send-back' || action === 'not-approve';
  return needsNote && note.trim() === '' ? 'Enter a note for the applicant' : null;
}

/** The scope check: all four questions answered, a decision chosen, and a reason unless it is the pilot. */
export function scopeFormError(answers: Partial<ScopeAnswers>, decision: ScopeFlag | null, reason: string): string | null {
  const answered = (['pathway', 'spoaReferrals', 'canReport', 'categoryOnList'] as const).every((key) => answers[key] !== undefined);
  if (!answered) return 'Answer every question';
  if (decision === null) return 'Choose a decision';
  return reasonRequired(decision) && reason.trim() === '' ? 'Enter a reason' : null;
}

/** Set live is offered only once the test notification has been answered from the registered phone. */
export function setLiveEnabled(decision: Decision): boolean {
  return decision.test.answeredAt !== undefined;
}

// ------------------------------------------------------------------------------- parsers

type Json = Record<string, unknown>;

function isRecord(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(value: unknown): string {
  if (typeof value !== 'string') throw new Error('expected a string');
  return value;
}

function optionalStr(value: unknown): string | undefined {
  return value === undefined || value === null ? undefined : str(value);
}

function list<T>(value: unknown, item: (v: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new Error('expected a list');
  return value.map(item);
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value === 'string' && (allowed as readonly string[]).includes(value)) return value as T;
  throw new Error('unexpected value');
}

function record(value: unknown): Json {
  if (!isRecord(value)) throw new Error('expected an object');
  return value;
}

const SCOPE_STATES: readonly ScopeRegistrationState[] = [
  'not-invited',
  'invited',
  'in-review',
  'live',
  'paused',
  'not-approved',
  'reverify',
];

export function parseScopeList(value: unknown): ScopeList {
  const body = record(value);
  return {
    entries: list(body.entries, (entry) => {
      const e = record(entry);
      const reason = optionalStr(e.reason);
      return {
        serviceId: str(e.serviceId),
        name: str(e.name),
        category: str(e.category),
        flag: oneOf(e.flag, SCOPE_FLAGS),
        registrationState: oneOf(e.registrationState, SCOPE_STATES),
        ...(reason ? { reason } : {}),
      };
    }),
  };
}

export function parseQueue(value: unknown): QueueResponse {
  const body = record(value);
  const counts: QueueResponse['counts'] = {};
  for (const tab of QUEUE_TABS) {
    const n = record(body.counts)[tab];
    if (typeof n !== 'number' || !Number.isInteger(n) || n < 0) throw new Error('expected a count');
    counts[tab] = n;
  }
  const tab = str(body.tab);
  if (!(QUEUE_TABS as readonly string[]).includes(tab)) throw new Error('expected a tab');
  return {
    tab: tab as QueueTab,
    counts,
    tabs: list(body.tabs, (item) => {
      const t = record(item);
      return { key: str(t.key), label: str(t.label), count: Number(t.count) };
    }),
    items: list(body.items, (item) => {
      const i = record(item);
      const category = optionalStr(i.category);
      return {
        id: str(i.id),
        serviceName: str(i.serviceName),
        state: str(i.state),
        submittedAt: str(i.submittedAt),
        submittedByRole: str(i.submittedByRole),
        ...(category ? { category } : {}),
      };
    }),
  };
}

const MANUAL = ['not-done', 'waiting', 'done'] as const;

export function parseOverview(value: unknown): Overview {
  const body = record(value);
  const by = record(body.registeredBy);
  const manual = record(body.manualChecks);
  const pathwayName = optionalStr(body.pathwayName);
  const callBack = body.callBack === undefined ? undefined : record(body.callBack);
  return {
    id: str(body.id),
    serviceName: str(body.serviceName),
    registeredBy: { name: str(by.name), role: str(by.role) },
    automaticChecks: list(body.automaticChecks, (check) => {
      const c = record(check);
      const action = optionalStr(c.action);
      if (typeof c.ok !== 'boolean') throw new Error('expected a flag');
      return { key: str(c.key), label: str(c.label), ok: c.ok, ...(action ? { action } : {}) };
    }),
    manualChecks: {
      callback: oneOf(manual.callback, ['not-done', 'done']),
      scope: oneOf(manual.scope, ['not-done', 'done']),
      criteria: oneOf(manual.criteria, MANUAL),
    },
    ...(pathwayName ? { pathwayName } : {}),
    ...(callBack
      ? {
          callBack: {
            numberToCall: str(callBack.numberToCall),
            ...(optionalStr(callBack.numberGiven) ? { numberGiven: optionalStr(callBack.numberGiven) } : {}),
            ...(optionalStr(callBack.directoryName) ? { directoryName: optionalStr(callBack.directoryName) } : {}),
          },
        }
      : {}),
  };
}

export function parseDecision(value: unknown): Decision {
  const body = record(value);
  const test = record(body.test);
  const sentAt = optionalStr(test.sentAt);
  const answeredAt = optionalStr(test.answeredAt);
  return {
    missing: list(body.missing, str),
    approvedBy: list(body.approvedBy, str),
    test: { ...(sentAt ? { sentAt } : {}), ...(answeredAt ? { answeredAt } : {}) },
    timeline: list(body.timeline, (item) => {
      const t = record(item);
      return { at: str(t.at), label: str(t.label) };
    }),
  };
}
