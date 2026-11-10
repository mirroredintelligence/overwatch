import type { StatusCode } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';

// Advisor v2: the capacity overview (DEC-1366), as GET /advisor-v2/capacity answers it. The two Needs attention
// lists are the shift lead's rules (lead_views.py): a stale figure shows no percentage and is never spare capacity.
// The five counts link to filtered lists under /advisor/v2/services. Pure.

export const V2_BROWSE_NOTE =
  'This page only looks services up. It opens no case and nothing is stored: not the postcode, the age or the needs.';

export type PressureRow = { serviceId: string; name: string; status: StatusCode; reason: string; usedPercent: number | null };
export type SpareRow = { serviceId: string; name: string; usedPercent: number; spare: number; unitLabel: string };
export type CapacityService = {
  serviceId: string;
  name: string;
  category: string;
  status: StatusCode;
  effectiveAvailable: number | null;
  overBy: number | null;
  unitLabel: string;
  reportedAt: string | null;
  figureUnavailable: boolean;
  lastFigure: number | null;
};
export type CountedStatus = 'accepting' | 'limited' | 'not-accepting' | 'over-capacity' | 'not-updated';
export type Overview = {
  counts: Record<CountedStatus, number>;
  attentionShown: number;
  underPressure: PressureRow[];
  underutilised: SpareRow[];
  services: CapacityService[];
};

type Raw = Record<string, unknown>;
const isRecord = (value: unknown): value is Raw => typeof value === 'object' && value !== null && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);
const whole = (value: unknown): number | null => (typeof value === 'number' && Number.isInteger(value) ? value : null);
const KNOWN: readonly StatusCode[] = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated', 'out-of-hours'];
const statusOf = (value: unknown): StatusCode => {
  const text = str(value);
  return text !== null && (KNOWN as readonly string[]).includes(text) ? (text as StatusCode) : 'not-updated';
};

const COUNT_KEYS: Record<string, CountedStatus> = {
  accepting: 'accepting',
  limited: 'limited',
  notAccepting: 'not-accepting',
  overCapacity: 'over-capacity',
  notUpdated: 'not-updated',
};

function pressureOf(value: unknown): PressureRow | null {
  if (!isRecord(value)) return null;
  const serviceId = str(value.serviceId);
  const name = str(value.name);
  const reason = str(value.reason);
  if (serviceId === null || name === null || reason === null) return null;
  return { serviceId, name, status: statusOf(value.status), reason, usedPercent: whole(value.usedPercent) };
}

function spareOf(value: unknown): SpareRow | null {
  if (!isRecord(value)) return null;
  const serviceId = str(value.serviceId);
  const name = str(value.name);
  const usedPercent = whole(value.usedPercent);
  const spare = whole(value.spare);
  // Only a current figure can be spare capacity: a row without one is not shown.
  if (serviceId === null || name === null || usedPercent === null || spare === null) return null;
  return { serviceId, name, usedPercent, spare, unitLabel: str(value.unitLabel) ?? '' };
}

function serviceOf(value: unknown): CapacityService | null {
  if (!isRecord(value)) return null;
  const serviceId = str(value.serviceId);
  const name = str(value.name);
  if (serviceId === null || name === null) return null;
  const status = statusOf(value.status);
  return {
    serviceId,
    name,
    category: str(value.category) ?? 'other',
    status,
    effectiveAvailable: whole(value.effectiveAvailable),
    overBy: whole(value.overBy),
    unitLabel: str(value.unitLabel) ?? '',
    reportedAt: str(value.reportedAt),
    figureUnavailable: value.figureUnavailable === true || status === 'not-updated',
    lastFigure: whole(value.lastFigure),
  };
}

function list<T>(value: unknown, read: (item: unknown) => T | null): T[] {
  return Array.isArray(value) ? value.map(read).filter((item): item is T => item !== null) : [];
}

/** The overview, or null when the answer is not shaped like one. */
export function parseOverview(body: unknown): Overview | null {
  if (!isRecord(body) || !isRecord(body.counts)) return null;
  const counts: Record<CountedStatus, number> = { accepting: 0, limited: 0, 'not-accepting': 0, 'over-capacity': 0, 'not-updated': 0 };
  for (const [key, status] of Object.entries(COUNT_KEYS)) {
    const count = whole(body.counts[key]);
    if (count === null) return null;
    counts[status] = count;
  }
  return {
    counts,
    attentionShown: whole(body.attentionShown) ?? 3,
    underPressure: list(body.underPressure, pressureOf),
    underutilised: list(body.underutilised, spareOf),
    services: list(body.services, serviceOf),
  };
}

/** A count's link: the filtered list of services under v2 (never the v1 list). */
export function statusHref(status: StatusCode): string {
  return `/advisor/v2/services?status=${status}`;
}

export function attentionShown<T>(items: readonly T[], limit: number): { shown: T[]; more: number } {
  return { shown: items.slice(0, limit), more: Math.max(0, items.length - limit) };
}

/** A service row as the v1 service card's summary row reads it. `now` is the page's clock, in milliseconds. */
export function capacityToOption(row: CapacityService, now: number): OptionView {
  const age = row.reportedAt === null ? null : Math.max(0, Math.floor((now - Date.parse(row.reportedAt)) / 1000));
  return {
    serviceId: row.serviceId,
    name: row.name,
    category: row.category,
    status: row.status,
    effectiveAvailable: row.effectiveAvailable,
    overBy: row.overBy,
    unitLabel: row.unitLabel === '' ? null : row.unitLabel,
    travelText: null,
    dataAgeSeconds: Number.isNaN(age) ? null : age,
    staleWarning: row.figureUnavailable,
    reportedAt: row.reportedAt,
    nextDueAt: null,
    cadence: null,
    lastFigure: row.lastFigure,
    overdue: false,
    figureUnavailable: row.figureUnavailable,
    criteriaVersion: null,
    fits: [],
    checks: [],
    phone: null,
    network: null,
    position: null,
    coverage: null,
    travel: null,
  };
}

/** The states chosen in `?status=a,b`, among the five that are counted; anything else is ignored. */
export function statusesFromQuery(value: string | string[] | undefined): CountedStatus[] {
  const text = Array.isArray(value) ? (value[0] ?? '') : (value ?? '');
  const named = new Set(text.split(',').map((part) => part.trim()));
  return COUNTED_STATUSES.filter((status) => named.has(status));
}

export const COUNTED_STATUSES: readonly CountedStatus[] = ['accepting', 'limited', 'over-capacity', 'not-accepting', 'not-updated'];
