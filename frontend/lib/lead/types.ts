import type { StatusCode } from '@/components/ui/StatusBadge';

// The shift lead's data as the browser sees it (W17). Every field comes from the BFF, never from a
// constant. A service's name and a figure are shown as the back end gave them; no telephone number
// is held here, only the last four digits of one.

export type LadderStep = 'prompt' | 'reminder' | 'phone-task' | 'escalate';

export type LadderRow = {
  step: LadderStep;
  /** ISO 8601 instant of the step. */
  at: string;
  done: boolean;
};

export type ChaseItem = {
  serviceId: string;
  name: string;
  /** When the report was due. */
  dueAt: string;
  overdueMinutes: number;
  /** The last figure, as words, for example "3 beds free". */
  lastValueText: string;
  ladder: LadderRow[];
};

export type GettingOldItem = {
  serviceId: string;
  name: string;
  reportedAt: string;
  nextDueAt: string;
  status: StatusCode;
};

export type CoveringItem = {
  serviceId: string;
  name: string;
  /** The last four digits of the registered number. */
  numberEnding: string;
  /** ISO 8601 instant the cover ends, or null for the usual contact. */
  until: string | null;
};

export type SystemCounts = {
  accepting: number;
  limited: number;
  notAccepting: number;
  overCapacity: number;
  notUpdated: number;
};

export type LeadOverview = {
  chasing: ChaseItem[];
  gettingOld: GettingOldItem[];
  covering: CoveringItem[];
  counts: SystemCounts;
  reportingToday: number;
};
