import type { StatusCode } from '@/components/ui/StatusBadge';
import type { LadderRow, LadderStep, LeadOverview } from './types';

// Reads the BFF's overview answer. A shape that is not the one the page knows is an error, never a
// partly filled page: an empty list would read as "nothing to chase" (H-330).

export class LeadParseError extends Error {
  constructor() {
    super('The shift lead overview could not be read.');
    this.name = 'LeadParseError';
  }
}

const STEPS: readonly LadderStep[] = ['prompt', 'reminder', 'phone-task', 'escalate'];
const STATUSES: readonly StatusCode[] = [
  'accepting',
  'limited',
  'not-accepting',
  'over-capacity',
  'not-updated',
  'out-of-hours',
  'last-known',
];

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0) throw new LeadParseError();
  return value;
}

function nullableText(value: unknown): string | null {
  if (value === null) return null;
  return text(value);
}

function count(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) throw new LeadParseError();
  return value;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new LeadParseError();
  return value;
}

function ladderRow(value: unknown): LadderRow {
  if (!isObject(value)) throw new LeadParseError();
  const step = STEPS.find((s) => s === value.step);
  if (step === undefined || typeof value.done !== 'boolean') throw new LeadParseError();
  return { step, at: text(value.at), done: value.done };
}

export function parseOverview(value: unknown): LeadOverview {
  if (!isObject(value) || !isObject(value.counts)) throw new LeadParseError();
  const counts = value.counts;
  return {
    chasing: list(value.chasing).map((item) => {
      if (!isObject(item)) throw new LeadParseError();
      return {
        serviceId: text(item.serviceId),
        name: text(item.name),
        dueAt: text(item.dueAt),
        overdueMinutes: count(item.overdueMinutes),
        lastValueText: text(item.lastValueText),
        ladder: list(item.ladder).map(ladderRow),
      };
    }),
    gettingOld: list(value.gettingOld).map((item) => {
      if (!isObject(item)) throw new LeadParseError();
      const status = STATUSES.find((s) => s === item.status);
      if (status === undefined) throw new LeadParseError();
      return {
        serviceId: text(item.serviceId),
        name: text(item.name),
        reportedAt: text(item.reportedAt),
        nextDueAt: text(item.nextDueAt),
        status,
      };
    }),
    covering: list(value.covering).map((item) => {
      if (!isObject(item)) throw new LeadParseError();
      return {
        serviceId: text(item.serviceId),
        name: text(item.name),
        numberEnding: text(item.numberEnding),
        until: nullableText(item.until),
      };
    }),
    counts: {
      accepting: count(counts.accepting),
      limited: count(counts.limited),
      notAccepting: count(counts.notAccepting),
      overCapacity: count(counts.overCapacity),
      notUpdated: count(counts.notUpdated),
    },
    reportingToday: count(value.reportingToday),
  };
}
