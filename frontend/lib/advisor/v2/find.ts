import type { StatusCode } from '@/components/ui/StatusBadge';
import { categoryLabel } from '@/lib/board/format';
import { PHONE_PATTERN, type OptionView } from '@/lib/advisor/options';

// Advisor v2: find a service (DEC-1366). The answer of POST /advisor-v2/find read into plain data. It is the same
// criteria as the v1 options (the back end's check), but nothing here is a ranking: the back end sends travel then
// name, the advisor may switch to name, and status never orders anything. A late, old or unknown figure is never the
// current capacity; the last figure is kept to show small. Pure.

const KNOWN_STATUS: readonly StatusCode[] = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated', 'out-of-hours'];

export type FoundService = {
  serviceId: string;
  name: string;
  category: string;
  status: StatusCode;
  effectiveAvailable: number | null;
  overBy: number | null;
  unitLabel: string | null;
  dataAgeSeconds: number | null;
  reportedAt: string | null;
  nextDueAt: string | null;
  cadence: string | null;
  overdue: boolean;
  staleWarning: boolean;
  figureUnavailable: boolean;
  lastFigure: number | null;
  criteriaVersion: number | null;
  fits: string[];
  warnings: string[];
  phone: string | null;
  travel: { low: number; high: number; source: string } | null;
};

export type FindRead = {
  services: FoundService[];
  notFound: boolean;
  generatedAt: string | null;
  /** How many services each group has in all (found or not), for "3 of 5 services". */
  groupTotals: Record<string, number>;
};

type Raw = Record<string, unknown>;

const isRecord = (value: unknown): value is Raw => typeof value === 'object' && value !== null && !Array.isArray(value);
const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);
const whole = (value: unknown): number | null => (typeof value === 'number' && Number.isInteger(value) ? value : null);
const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []);

function travelOf(value: unknown): FoundService['travel'] {
  if (!isRecord(value)) return null;
  const low = whole(value.low);
  const high = whole(value.high);
  return low === null || high === null ? null : { low, high, source: str(value.source) ?? '' };
}

function serviceOf(value: unknown): FoundService | null {
  if (!isRecord(value)) return null;
  const serviceId = str(value.serviceId);
  const name = str(value.name);
  if (serviceId === null || name === null) return null;
  const rawStatus = str(value.status);
  const status = rawStatus !== null && (KNOWN_STATUS as readonly string[]).includes(rawStatus) ? (rawStatus as StatusCode) : 'not-updated';
  const phone = str(value.phone);
  return {
    serviceId,
    name,
    category: str(value.category) ?? 'other',
    status,
    effectiveAvailable: whole(value.effectiveAvailable),
    overBy: whole(value.overBy),
    unitLabel: str(value.unitLabel),
    dataAgeSeconds: whole(value.dataAgeSeconds),
    reportedAt: str(value.reportedAt),
    nextDueAt: str(value.nextDueAt),
    cadence: str(value.cadence),
    overdue: value.overdue === true,
    staleWarning: value.staleWarning === true,
    // The back end's word, and never less cautious than the status: a status that is not known or not updated
    // is not a current figure whatever the flag says.
    figureUnavailable: value.figureUnavailable === true || status === 'not-updated',
    lastFigure: whole(value.lastFigure),
    criteriaVersion: whole(value.criteriaVersion),
    fits: strings(value.fits),
    warnings: strings(value.warnings),
    phone: phone !== null && PHONE_PATTERN.test(phone) ? phone : null,
    travel: travelOf(value.travel),
  };
}

/** The services in the order the back end sent them, or null when the answer is not shaped like one. */
export function parseFind(body: unknown): FindRead | null {
  if (!isRecord(body) || !Array.isArray(body.services)) return null;
  const services = body.services.map(serviceOf).filter((item): item is FoundService => item !== null);
  const groupTotals: Record<string, number> = {};
  if (isRecord(body.groupTotals)) {
    for (const [key, count] of Object.entries(body.groupTotals)) {
      if (typeof count === 'number' && Number.isInteger(count) && count >= 0 && /^[a-z][a-z0-9-]{0,63}$/.test(key)) groupTotals[key] = count;
    }
  }
  return { services, notFound: body.notFound === true, generatedAt: str(body.generatedAt), groupTotals };
}

function travelText(travel: FoundService['travel']): string | null {
  if (travel === null) return null;
  return travel.low === travel.high ? `about ${travel.low} min` : `about ${travel.low} to ${travel.high} min`;
}

/** The service as the v1 service card reads it (ServiceCard), so the card is reused as it is. */
export function toOption(item: FoundService): OptionView {
  return {
    serviceId: item.serviceId,
    name: item.name,
    category: item.category,
    status: item.status,
    effectiveAvailable: item.effectiveAvailable,
    overBy: item.overBy,
    unitLabel: item.unitLabel,
    travelText: travelText(item.travel),
    dataAgeSeconds: item.dataAgeSeconds,
    staleWarning: item.staleWarning,
    reportedAt: item.reportedAt,
    nextDueAt: item.nextDueAt,
    cadence: item.cadence,
    lastFigure: item.lastFigure,
    overdue: item.overdue,
    figureUnavailable: item.figureUnavailable,
    criteriaVersion: item.criteriaVersion,
    fits: item.fits,
    checks: item.warnings,
    phone: item.phone,
    network: null,
    position: null,
    coverage: null,
    travel: item.travel === null ? null : { ...item.travel, legs: [] },
  };
}

export type Group = { category: string; label: string; services: FoundService[] };

/** One group per service category, by the group's name. Never by how many are accepting. */
export function groupsOf(services: readonly FoundService[]): Group[] {
  const byCategory = new Map<string, FoundService[]>();
  for (const item of services) byCategory.set(item.category, [...(byCategory.get(item.category) ?? []), item]);
  return [...byCategory.entries()]
    .map(([category, list]) => ({ category, label: categoryLabel(category), services: list }))
    .sort((a, b) => a.label.localeCompare(b.label) || a.category.localeCompare(b.category));
}

export type ServiceOrder = 'travel' | 'name';

/** Travel keeps the back end's order (travel, then name). Name is by name then id. Status plays no part in either. */
export function orderServices(services: readonly FoundService[], order: ServiceOrder): FoundService[] {
  if (order === 'travel') return [...services];
  return [...services].sort((a, b) => a.name.localeCompare(b.name) || a.serviceId.localeCompare(b.serviceId));
}
