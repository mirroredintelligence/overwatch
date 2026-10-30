import { londonTime } from '@/lib/board/format';
import type { BoardEntry } from '@/lib/board/types';
import { ALERT_KINDS, type AlertKind } from './alertPrefs';

// An open alert as the executive's screens show it (W40). Built from the back end's alert Task (R12)
// and the board's entry for its service. An alert holds no free text (H-09), so none is shown.

export type AlertItem = {
  id: string;
  kind: AlertKind;
  serviceId: string | null;
  serviceName: string | null;
  detail: string | null;
  /** ISO 8601 UTC, to the second, as the back end sent it. */
  raisedAt: string;
  state: 'new' | 'escalated';
  escalatesAt: string | null;
  escalatesTo: 'deputy' | null;
};

const TASK_INPUT_KIND = 'alert-kind';
const KIND_PHRASE: Readonly<Record<AlertKind, string>> = {
  'service-closed': 'closed unexpectedly',
  'over-capacity': 'over capacity',
  'not-updated': 'has not updated',
  'system-pressure': 'system pressure rising',
};

type Task = Record<string, unknown>;

/** An instant as the back end writes it, without fractions: `2026-10-23T13:04:00Z`. */
export function instantText(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) throw new Error('not an instant');
  return parsed.toISOString().replace('.000Z', 'Z');
}

function kindOf(task: Task): AlertKind {
  const extensions = Array.isArray(task.extension) ? (task.extension as Record<string, unknown>[]) : [];
  const kind = extensions.find((item) => typeof item.url === 'string' && item.url.endsWith(`/${TASK_INPUT_KIND}`))?.valueCode;
  if (typeof kind !== 'string' || !(ALERT_KINDS as readonly string[]).includes(kind)) throw new Error('an alert has no known kind');
  return kind as AlertKind;
}

function serviceIdOf(task: Task): string | null {
  const focus = task.focus as { reference?: unknown } | undefined;
  const reference = typeof focus?.reference === 'string' ? focus.reference : '';
  return reference.startsWith('HealthcareService/') ? reference.slice('HealthcareService/'.length) : null;
}

/** The alert as the screens show it. `entryFor` reads the board's entry for a service, if the board has it. */
export function alertItemFromTask(task: unknown, entryFor: (serviceId: string) => BoardEntry | undefined): AlertItem {
  if (typeof task !== 'object' || task === null) throw new Error('an alert must be a Task');
  const record = task as Task;
  if (typeof record.id !== 'string' || record.id === '') throw new Error('an alert has no id');
  const kind = kindOf(record);
  const serviceId = serviceIdOf(record);
  const entry = serviceId === null ? undefined : entryFor(serviceId);
  const status = (((record.businessStatus as { coding?: { code?: unknown }[] } | undefined)?.coding ?? [])[0]?.code);
  if (status !== 'new' && status !== 'escalated') throw new Error('an alert has an unknown state');
  const raised = typeof record.authoredOn === 'string' ? instantText(record.authoredOn) : null;
  if (raised === null) throw new Error('an alert has no time');
  const due = (record.executionPeriod as { end?: unknown } | undefined)?.end;
  const escalatesAt = typeof due === 'string' ? instantText(due) : null;
  return {
    id: record.id,
    kind,
    serviceId,
    serviceName: entry?.name ?? null,
    detail: kind === 'over-capacity' && entry?.overBy !== null && entry?.overBy !== undefined && entry.overBy > 0 ? `+${entry.overBy}` : null,
    raisedAt: raised,
    state: status,
    escalatesAt,
    escalatesTo: escalatesAt === null ? null : 'deputy',
  };
}

/** The title of an alert card: the service and what happened. */
export function alertTitle(item: AlertItem): string {
  return `${item.serviceName ?? 'A service'} ${KIND_PHRASE[item.kind]}`;
}

/** "HH:MM" in London time, for the card's state line. */
export function alertTime(instant: string): string {
  return londonTime(instant);
}
