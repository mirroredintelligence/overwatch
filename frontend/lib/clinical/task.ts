import { instantText } from '@/lib/exec/alerts';
import { AGE_BANDS, NEEDS, URGENCIES } from '@/lib/advisor/codes';
import { ADVICE_CHOICES, ADVICE_REASONS, REQUEST_URGENCIES, REQUEST_WHYS } from './advice';

// A clinical advice request as the back end's Task gives it (R13, DEC-774), read for the screens.
//
// The Task names the case, the urgency and the reason, and carries the case's glance: its number, age
// band, needs, urgency and NEWS2. It never carries a postcode, a district or a person's id, and this
// reader keeps none whatever the Task holds. A Task with no case number has no glance: the case could
// not be read, and the screens say so rather than showing a guess (DEC-855).

export type Urgency = 'now' | 'within-15-min';
export type RequestStatus = 'requested' | 'in-progress' | 'completed';

export type Glance = {
  caseReference: string;
  ageBand: string | null;
  needs: string[];
  caseUrgency: string | null;
  news2: number | null;
};

export type GivenAdvice = { choice: string; reason: string | null; note: string | null; at: string | null };

export type ClinicalRequest = {
  id: string;
  status: RequestStatus;
  urgency: Urgency;
  why: string;
  /** ISO 8601 UTC, to the second. */
  requestedAt: string;
  caseId: string;
  glance: Glance | null;
  /** When a held request returns to the queue; null when nobody holds it. */
  returnsAt: string | null;
  advice: GivenAdvice | null;
  /** The name of the service the advisor was asking about (KI-768); null when they asked about the case. */
  service: string | null;
};

const TASK_INPUT = 'task-input';
const SERVICE_REQUEST = 'ServiceRequest/';
const STATUSES: readonly string[] = ['requested', 'in-progress', 'completed'];

type Extension = Record<string, unknown>;

function extensionsOf(task: Record<string, unknown>, name: string): Extension[] {
  const all = Array.isArray(task.extension) ? (task.extension as Extension[]) : [];
  return all.filter((item) => typeof item.url === 'string' && item.url.endsWith(`/${TASK_INPUT}/${name}`));
}

function code(task: Record<string, unknown>, name: string): string | null {
  const value = extensionsOf(task, name)[0]?.valueCode;
  return typeof value === 'string' ? value : null;
}

function text(task: Record<string, unknown>, name: string): string | null {
  const value = extensionsOf(task, name)[0]?.valueString;
  return typeof value === 'string' ? value : null;
}

function instant(task: Record<string, unknown>, name: string): string | null {
  const value = extensionsOf(task, name)[0]?.valueDateTime;
  return typeof value === 'string' ? instantText(value) : null;
}

const known = (list: readonly string[], value: string | null, what: string): string | null => {
  if (value !== null && !list.includes(value)) throw new Error(`${what} is not known`);
  return value;
};

function glanceOf(task: Record<string, unknown>): Glance | null {
  const caseReference = text(task, 'case-reference');
  if (caseReference === null || caseReference === '') return null;
  const news2 = extensionsOf(task, 'news2')[0]?.valueInteger;
  return {
    caseReference,
    ageBand: known(AGE_BANDS.map((band) => band.code), code(task, 'age-band'), 'age band'),
    needs: extensionsOf(task, 'need').flatMap((item) => {
      const value = item.valueCode;
      if (typeof value !== 'string') return [];
      known(NEEDS.map((need) => need.code), value, 'need');
      return [value];
    }),
    caseUrgency: known(URGENCIES.map((urgency) => urgency.code), code(task, 'case-urgency'), 'case urgency'),
    news2: typeof news2 === 'number' ? news2 : null,
  };
}

function adviceOf(task: Record<string, unknown>): GivenAdvice | null {
  const choice = known(ADVICE_CHOICES, code(task, 'advice-choice'), 'advice choice');
  if (choice === null) return null;
  return {
    choice,
    reason: known(ADVICE_REASONS, code(task, 'advice-reason'), 'advice reason'),
    note: text(task, 'advice-note'),
    at: instant(task, 'advised-at'),
  };
}

function serviceOf(task: Record<string, unknown>): string | null {
  const name = text(task, 'service');
  return name === null || name.trim() === '' ? null : name;
}

export function clinicalRequestFromTask(task: unknown): ClinicalRequest {
  if (typeof task !== 'object' || task === null) throw new Error('a clinical request must be a Task');
  const record = task as Record<string, unknown>;
  if (typeof record.id !== 'string' || record.id === '') throw new Error('a clinical request has no id');
  const status = record.status;
  if (typeof status !== 'string' || !STATUSES.includes(status)) throw new Error('status is not known');
  const urgency = code(record, 'urgency');
  if (urgency === null || !(REQUEST_URGENCIES as readonly string[]).includes(urgency)) throw new Error('urgency is not known');
  const why = code(record, 'why');
  if (why === null || !(REQUEST_WHYS as readonly string[]).includes(why)) throw new Error('why is not known');
  const focus = record.focus as { reference?: unknown } | undefined;
  const reference = typeof focus?.reference === 'string' ? focus.reference : '';
  if (!reference.startsWith(SERVICE_REQUEST)) throw new Error('a clinical request names no case');
  if (typeof record.authoredOn !== 'string') throw new Error('a clinical request has no time');
  return {
    id: record.id,
    status: status as RequestStatus,
    urgency: urgency as Urgency,
    why,
    requestedAt: instantText(record.authoredOn),
    caseId: reference.slice(SERVICE_REQUEST.length),
    glance: glanceOf(record),
    returnsAt: instant(record, 'returns-at'),
    advice: adviceOf(record),
    service: serviceOf(record),
  };
}
