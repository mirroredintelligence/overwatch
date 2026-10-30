// Pure rules and parsers for the registration pages (W28, W29). No I/O: the components and the
// BFF call these, so the wording and the gates are decided in one place.
import { londonTime } from '@/lib/board/format';
import type {
  Decision,
  Overview,
  QueueItem,
  QueueResponse,
  QueueTab,
  ScopeEntry,
  ScopeFlag,
  ScopeList,
  ScopeRegistrationState,
} from './types';

export const SCOPE_FLAGS: readonly ScopeFlag[] = ['in-pilot', 'later', 'out-of-scope'];
export const QUEUE_TABS: readonly QueueTab[] = ['to-review', 'waiting', 'go-live', 'done'];
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
  const count = (n: number | undefined) => (n === undefined ? '' : ` (${n})`);
  switch (tab) {
    case 'to-review':
      return `To review${count(counts?.toReview)}`;
    case 'waiting':
      return `Waiting${count(counts?.waiting)}`;
    case 'go-live':
      return `Go live${count(counts?.goLive)}`;
    case 'done':
      return 'Done';
  }
}

export function submittedText(item: QueueItem): string {
  return `Submitted ${londonTime(item.submittedAt)} by ${item.submittedByRole}`;
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
  const counts = record(body.counts);
  const number = (v: unknown) => {
    if (typeof v !== 'number' || !Number.isInteger(v) || v < 0) throw new Error('expected a count');
    return v;
  };
  return {
    counts: { toReview: number(counts.toReview), waiting: number(counts.waiting), goLive: number(counts.goLive) },
    items: list(body.items, (item) => {
      const i = record(item);
      const firstIssue = optionalStr(i.firstIssue);
      return {
        id: str(i.id),
        serviceName: str(i.serviceName),
        state: str(i.state),
        submittedAt: str(i.submittedAt),
        submittedByRole: str(i.submittedByRole),
        ...(firstIssue ? { firstIssue } : {}),
      };
    }),
  };
}

const MANUAL = ['not-done', 'waiting', 'done'] as const;

export function parseOverview(value: unknown): Overview {
  const body = record(value);
  const by = record(body.registeredBy);
  const manual = record(body.manualChecks);
  const callBackNumber = optionalStr(body.callBackNumber);
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
    ...(callBackNumber ? { callBackNumber } : {}),
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
