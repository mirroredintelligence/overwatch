import { instantText } from '@/lib/exec/alerts';
import { REQUEST_URGENCIES, REQUEST_WHYS } from './advice';

// A queued clinical request as the screens show it (W44). The back end's queue (R13) names the case, the
// urgency and the reason, and nothing else: no age band, no needs, no referrer. The screens show only that.

export type Urgency = 'now' | 'within-15-min';
export type QueueItem = {
  id: string;
  urgency: Urgency;
  why: string;
  /** ISO 8601 UTC, to the second. */
  requestedAt: string;
  status: string;
  caseId: string;
};

const TASK_INPUT = 'task-input';
const SERVICE_REQUEST = 'ServiceRequest/';

export const WHY_TEXT: Readonly<Record<string, string>> = {
  'borderline-criteria': 'Borderline criteria',
  'unsure-of-urgency': 'Unsure of urgency',
  other: 'Other',
};

export function urgencyText(urgency: Urgency): string {
  return urgency === 'now' ? 'Now' : 'Within 15 min';
}

function inputOf(task: Record<string, unknown>, name: string): unknown {
  const extensions = Array.isArray(task.extension) ? (task.extension as Record<string, unknown>[]) : [];
  return extensions.find((item) => typeof item.url === 'string' && item.url.endsWith(`/${TASK_INPUT}/${name}`))?.valueCode;
}

export function queueItemFromTask(task: unknown): QueueItem {
  if (typeof task !== 'object' || task === null) throw new Error('a queued request must be a Task');
  const record = task as Record<string, unknown>;
  if (typeof record.id !== 'string' || record.id === '') throw new Error('a queued request has no id');
  const urgency = inputOf(record, 'urgency');
  if (typeof urgency !== 'string' || !(REQUEST_URGENCIES as readonly string[]).includes(urgency)) {
    throw new Error('urgency is not known');
  }
  const why = inputOf(record, 'why');
  if (typeof why !== 'string' || !(REQUEST_WHYS as readonly string[]).includes(why)) throw new Error('why is not known');
  const focus = record.focus as { reference?: unknown } | undefined;
  const reference = typeof focus?.reference === 'string' ? focus.reference : '';
  if (!reference.startsWith(SERVICE_REQUEST)) throw new Error('a queued request names no case');
  if (typeof record.authoredOn !== 'string') throw new Error('a queued request has no time');
  return {
    id: record.id,
    urgency: urgency as Urgency,
    why,
    requestedAt: instantText(record.authoredOn),
    status: typeof record.status === 'string' ? record.status : 'requested',
    caseId: reference.slice(SERVICE_REQUEST.length),
  };
}
