import type { Decision, Overview, QueueItem, QueueResponse, QueueTab } from './types';

// The reviewer's reads, mapped from the back end's answers (W7B A4) to the shapes the reviewer's pages
// use (DEC-907). Pure, so the BFF maps and the tests read the same rule. Nothing the page does not show
// is kept: no phone number, no organisation name, no applicant number, no tenant. A call-back number
// is not passed: the back end holds none to give (K-W8C-2). Each mapper answers null for an answer that
// is not the shape the page needs, and the route answers 503.

export const QUEUE_TAB_KEYS: readonly QueueTab[] = ['waiting', 'sent-back', 'approved', 'live', 'not-approved'];

type Json = Record<string, unknown>;

function isRecord(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function count(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : undefined;
}

export function queueFromBackend(raw: unknown): QueueResponse | null {
  if (!isRecord(raw)) return null;
  const tab = raw.tab;
  if (typeof tab !== 'string' || !(QUEUE_TAB_KEYS as readonly string[]).includes(tab)) return null;
  if (!isRecord(raw.counts) || !Array.isArray(raw.tabs) || !Array.isArray(raw.registrations)) return null;

  const counts: Partial<Record<QueueTab, number>> = {};
  for (const key of QUEUE_TAB_KEYS) {
    const n = count(raw.counts[key]);
    if (n === undefined) return null;
    counts[key] = n;
  }
  const tabs = raw.tabs.map((item) => {
    if (!isRecord(item)) return null;
    const key = text(item.key);
    const label = text(item.label);
    const n = count(item.count);
    if (key === undefined || label === undefined || n === undefined) return null;
    return { key, label, count: n };
  });
  if (tabs.some((item) => item === null)) return null;

  const items: QueueItem[] = [];
  for (const row of raw.registrations) {
    if (!isRecord(row)) return null;
    const id = text(row.registrationId);
    const serviceName = text(row.serviceName);
    const state = text(row.status);
    const submittedAt = text(row.submittedAt);
    const by = isRecord(row.registeredBy) ? row.registeredBy : undefined;
    const role = text(by?.role);
    if (id === undefined || serviceName === undefined || state === undefined || submittedAt === undefined || role === undefined) return null;
    const category = text(row.category);
    items.push({
      id,
      serviceName,
      state,
      submittedAt,
      submittedByRole: role,
      ...(category !== undefined ? { category } : {}),
    });
  }
  return { tab: tab as QueueTab, counts, tabs: tabs as NonNullable<(typeof tabs)[number]>[], items };
}

export function overviewFromBackend(raw: unknown): Overview | null {
  if (!isRecord(raw)) return null;
  const id = text(raw.registrationId);
  const serviceName = text(raw.serviceName);
  if (id === undefined || serviceName === undefined || !Array.isArray(raw.checks)) return null;
  const by = isRecord(raw.registeredBy) ? raw.registeredBy : undefined;
  const role = text(by?.role);
  if (role === undefined) return null;

  const automaticChecks = raw.checks.map((check) => {
    if (!isRecord(check)) return null;
    const key = text(check.name);
    const label = text(check.message);
    if (key === undefined || label === undefined || typeof check.ok !== 'boolean') return null;
    const explained = text(check.explainedNote);
    return { key, label, ok: check.ok, ...(explained !== undefined ? { action: explained } : {}) };
  });
  if (automaticChecks.some((check) => check === null)) return null;

  const callBack = isRecord(raw.callBack) ? raw.callBack : undefined;
  const directoryName = text(callBack?.directoryName);
  const pathwayName = text(callBack?.pathwayName);
  return {
    id,
    serviceName,
    registeredBy: { name: text(by?.contactName) ?? '', role },
    automaticChecks: automaticChecks as NonNullable<(typeof automaticChecks)[number]>[],
    manualChecks: {
      callback: raw.callbackConfirmed === true ? 'done' : 'not-done',
      scope: raw.scope !== null && raw.scope !== undefined ? 'done' : 'not-done',
      criteria: raw.criteriaApproved === true ? 'done' : 'not-done',
    },
    ...(directoryName !== undefined ? { callBack: { directoryName } } : {}),
    ...(pathwayName !== undefined ? { pathwayName } : {}),
  };
}

export function decisionFromBackend(raw: unknown): Decision | null {
  if (!isRecord(raw) || !Array.isArray(raw.missing) || !Array.isArray(raw.approvals) || !Array.isArray(raw.timeline)) return null;
  const missing = raw.missing.filter((item): item is string => typeof item === 'string');
  if (missing.length !== raw.missing.length) return null;
  const approvedBy: string[] = [];
  for (const approval of raw.approvals) {
    if (!isRecord(approval)) return null;
    const label = text(approval.label);
    if (label === undefined || typeof approval.done !== 'boolean') return null;
    if (approval.done) approvedBy.push(label);
  }
  const timeline: Decision['timeline'] = [];
  for (const item of raw.timeline) {
    if (!isRecord(item)) return null;
    const at = text(item.at);
    const label = text(item.event);
    if (at === undefined || label === undefined) return null;
    timeline.push({ at, label });
  }
  const test = isRecord(raw.test) ? raw.test : undefined;
  const sentAt = text(test?.sentAt);
  return { missing, approvedBy, test: sentAt !== undefined ? { sentAt } : {}, timeline };
}
