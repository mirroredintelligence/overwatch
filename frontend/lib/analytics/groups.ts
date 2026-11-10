import { categoryLabel } from '@/lib/board/format';
import { type BrowseRow } from '@/lib/advisor/servicesBrowse';
import { agoText } from '@/lib/lead/format';
import type { AnalyticsService } from './types';

// The groupings of the Analytics overview (DEC-1368). A service that covers several districts is counted in each; a
// service that covers none goes in "Not placed", never dropped. Everything is ordered by name, never by status.

export const NOT_PLACED = '__not-placed';

/** The eight service categories in the board's order. */
export const CATEGORIES: readonly string[] = [
  'urgent-community-response',
  'same-day-emergency-care',
  'inpatient-beds',
  'hospital-at-home-or-virtual-ward',
  'reablement',
  'urgent-treatment',
  'mental-health-crisis',
  'other',
];

export type StatusTally = {
  accepting: number;
  limited: number;
  'not-accepting': number;
  'over-capacity': number;
  'not-updated': number;
};

export type Group = {
  key: string;
  label: string;
  services: AnalyticsService[];
  counts: StatusTally;
};

export function statusCounts(services: readonly AnalyticsService[]): StatusTally {
  const counts: StatusTally = { accepting: 0, limited: 0, 'not-accepting': 0, 'over-capacity': 0, 'not-updated': 0 };
  for (const service of services) {
    if (service.status in counts) counts[service.status as keyof StatusTally] += 1;
  }
  return counts;
}

const byName = (a: AnalyticsService, b: AnalyticsService) => a.name.localeCompare(b.name) || a.serviceId.localeCompare(b.serviceId);

function group(key: string, label: string, services: AnalyticsService[]): Group {
  const sorted = [...services].sort(byName);
  return { key, label, services: sorted, counts: statusCounts(sorted) };
}

/** One group per district by name, and "Not placed" last when a service covers no district. */
export function districtGroups(services: readonly AnalyticsService[]): Group[] {
  const by = new Map<string, AnalyticsService[]>();
  const unplaced: AnalyticsService[] = [];
  for (const service of services) {
    if (service.districts.length === 0) unplaced.push(service);
    for (const district of service.districts) by.set(district, [...(by.get(district) ?? []), service]);
  }
  const groups = [...by.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([district, members]) => group(district, district, members));
  if (unplaced.length > 0) groups.push(group(NOT_PLACED, 'Not placed', unplaced));
  return groups;
}

/** All eight categories, in the board's order, an empty one included. A code the page does not know is added last. */
export function categoryGroups(services: readonly AnalyticsService[]): Group[] {
  const unknown = [...new Set(services.map((service) => service.category))].filter((code) => !CATEGORIES.includes(code)).sort();
  return [...CATEGORIES, ...unknown].map((code) =>
    group(
      code,
      categoryLabel(code),
      services.filter((service) => service.category === code),
    ),
  );
}

export type DrillTarget = { kind: 'district' | 'group' | 'status'; key: string };

export type DrillRow = BrowseRow & { href: string };

export function inTarget(service: AnalyticsService, target: DrillTarget): boolean {
  if (target.kind === 'status') return service.status === target.key;
  if (target.kind === 'group') return service.category === target.key;
  return target.key === NOT_PLACED ? service.districts.length === 0 : service.districts.includes(target.key);
}

function figureText(service: AnalyticsService): string | null {
  if (!service.figureCurrent) return null;
  if (service.status === 'over-capacity' && service.overBy !== null) return `+${service.overBy}`;
  return service.available === null ? null : String(service.available);
}

/** The services of a district, group or status by name, with the figure only when it is current. */
export function drillRows(services: readonly AnalyticsService[], target: DrillTarget, now: number = Date.now()): DrillRow[] {
  return services
    .filter((service) => inTarget(service, target))
    .sort(byName)
    .map((service) => ({
      serviceId: service.serviceId,
      name: service.name,
      category: service.category,
      status: service.status,
      figure: figureText(service),
      unitLabel: service.unitLabel,
      updated: service.reportedAt === null ? 'No report yet' : `Updated ${agoText(service.reportedAt, now)}`,
      href: `/analytics/services/${encodeURIComponent(service.serviceId)}`,
    }));
}
