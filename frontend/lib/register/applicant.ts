import type { StepName } from './types';

// The applicant's reads, mapped from the back end's answers (W7B A1, routes_registration_views.py)
// to the shapes the screens use (DEC-904, DEC-905). What a screen shows is kept; a whole phone number,
// an address beyond its label and a tenant are never passed on. Pure, so the browser's tests and the
// BFF share it. Each mapper answers null for an answer that is not the shape the screens need.

export const STEP_ORDER: readonly StepName[] = ['organisation', 'location', 'service', 'reporting', 'api'];
const REGISTRATION_STATUSES = [
  'invited',
  'draft',
  'submitted',
  'in-review',
  'needs-changes',
  'approved',
  'live',
  'not-approved',
  'paused',
  'reverify',
] as const;
const STEP_STATES = ['complete', 'needs-attention', 'not-started'] as const;
const MAX_ADDRESSES = 20;

export type StepProblem = { field: string; message: string };
export type RecordStep = { state: 'complete' | 'needs-attention' | 'not-started'; values: Record<string, unknown>; problems: StepProblem[] };
export type RecordView = { id: string; status: string; serviceName: string; steps: Partial<Record<StepName, RecordStep>> };
export type ReviewRow = { key: string; status: 'complete' | 'needs-attention'; summary: string };
export type MyService = { id: string; serviceName: string; state: 'active' | 'pending-approval' | 'review-due' | 'not-approved'; detail: string };
export type StatusView = {
  status: string;
  serviceName: string;
  submittedAt?: string;
  notes?: string[];
  noteFrom?: { role: string };
  reason?: string;
  firstPromptAt?: string;
  details?: { spoaPhone?: string; criteriaOwner?: string; reportingPhoneEnding?: string };
};

type Json = Record<string, unknown>;

function isRecord(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value !== '' ? value : undefined;
}

function isStatus(value: unknown): value is string {
  return typeof value === 'string' && (REGISTRATION_STATUSES as readonly string[]).includes(value);
}

/** A stored value the page may hold: a number is never passed, only its last three digits (DEC-904). */
function valuesOf(raw: unknown): Record<string, unknown> {
  if (!isRecord(raw)) return {};
  const values: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (value === null || value === undefined) continue;
    if (key === 'contactPhone') {
      if (typeof value === 'string' && value.length >= 3) values.contactPhoneEnding = value.slice(-3);
      continue;
    }
    if (key === 'contactMobile' || key === 'contactMobileNumber') continue;
    values[key] = value;
  }
  return values;
}

function problemsOf(raw: unknown): StepProblem[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item): StepProblem[] => {
    if (!isRecord(item) || typeof item.field !== 'string' || typeof item.message !== 'string') return [];
    return [{ field: item.field, message: item.message }];
  });
}

/** The registration as the applicant's screens use it, or null for an answer they cannot use. */
export function viewFromRecord(record: unknown): RecordView | null {
  if (!isRecord(record)) return null;
  const id = text(record.registrationId);
  const serviceName = text(record.serviceName);
  if (id === undefined || serviceName === undefined || !isStatus(record.status)) return null;
  if (!isRecord(record.steps)) return null;
  const steps: Partial<Record<StepName, RecordStep>> = {};
  for (const name of STEP_ORDER) {
    const step = record.steps[name];
    if (!isRecord(step)) continue;
    const state = step.state;
    if (typeof state !== 'string' || !(STEP_STATES as readonly string[]).includes(state)) return null;
    steps[name] = { state: state as RecordStep['state'], values: valuesOf(step.values), problems: problemsOf(step.problems) };
  }
  return { id, status: record.status, serviceName, steps };
}

/** One row per answered step, complete or needing attention, with the words the back end gave. */
export function reviewRowsFrom(view: RecordView): ReviewRow[] {
  const rows: ReviewRow[] = [];
  for (const name of STEP_ORDER) {
    const step = view.steps[name];
    if (step === undefined || step.state === 'not-started') continue;
    rows.push({
      key: name,
      status: step.state,
      summary: step.problems.map((problem) => problem.message).join(' '),
    });
  }
  return rows;
}

const MY_SERVICE_BY_STATUS: Partial<Record<string, { state: MyService['state']; detail: string }>> = {
  live: { state: 'active', detail: 'Live' },
  paused: { state: 'active', detail: 'Paused by the shift lead' },
  reverify: { state: 'review-due', detail: 'Check your details again' },
  submitted: { state: 'pending-approval', detail: 'Waiting for the shift lead' },
  'in-review': { state: 'pending-approval', detail: 'Waiting for the shift lead' },
  'needs-changes': { state: 'pending-approval', detail: 'The shift lead has sent it back' },
  approved: { state: 'pending-approval', detail: 'Approved. Going live soon.' },
  'not-approved': { state: 'not-approved', detail: 'Not approved' },
};

/** The applicant's services. A registration nobody has sent (invited, draft) is not listed here. */
export function myServicesFrom(raw: unknown): MyService[] | null {
  if (!isRecord(raw) || !Array.isArray(raw.registrations)) return null;
  const rows: MyService[] = [];
  for (const item of raw.registrations) {
    if (!isRecord(item)) continue;
    const mapped = typeof item.status === 'string' ? MY_SERVICE_BY_STATUS[item.status] : undefined;
    const id = text(item.registrationId);
    const serviceName = text(item.serviceName);
    if (mapped === undefined || id === undefined || serviceName === undefined) continue;
    rows.push({ id, serviceName, state: mapped.state, detail: mapped.detail });
  }
  return rows;
}

/** The applicant's status page, from the back end's status answer. Nothing it does not show. */
export function statusFrom(raw: unknown): StatusView | null {
  if (!isRecord(raw)) return null;
  const serviceName = text(raw.serviceName);
  if (!isStatus(raw.status) || serviceName === undefined) return null;
  const view: StatusView = { status: raw.status, serviceName };
  const submittedAt = text(raw.submittedAt);
  if (submittedAt !== undefined) view.submittedAt = submittedAt;
  const note = text(raw.note);
  if (note !== undefined) view.notes = [note];
  const from = text(raw.noteFrom);
  if (from !== undefined) view.noteFrom = { role: from };
  const reason = text(raw.reason);
  if (reason !== undefined) view.reason = reason;
  const firstPromptAt = text(raw.firstPromptAt);
  if (firstPromptAt !== undefined) view.firstPromptAt = firstPromptAt;
  if (isRecord(raw.details)) {
    const details: NonNullable<StatusView['details']> = {};
    const spoaPhone = text(raw.details.spoaPhone);
    const criteriaOwner = text(raw.details.criteriaOwner);
    const reportingPhoneEnding = text(raw.details.reportingPhoneEnding);
    if (spoaPhone !== undefined) details.spoaPhone = spoaPhone;
    if (criteriaOwner !== undefined) details.criteriaOwner = criteriaOwner;
    if (reportingPhoneEnding !== undefined) details.reportingPhoneEnding = reportingPhoneEnding;
    view.details = details;
  }
  return view;
}

/** The address lookup's list, at most twenty: the id and the label, nothing else. */
export function addressesFrom(raw: unknown): { id: string; label: string }[] | null {
  if (!isRecord(raw) || !Array.isArray(raw.addresses)) return null;
  const list: { id: string; label: string }[] = [];
  for (const item of raw.addresses) {
    if (list.length === MAX_ADDRESSES) break;
    if (!isRecord(item)) continue;
    const id = text(item.id);
    const label = text(item.label);
    if (id !== undefined && label !== undefined) list.push({ id, label });
  }
  return list;
}
