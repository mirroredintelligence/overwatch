import type { StatusCode } from '@/components/ui/StatusBadge';
import { DISTRICT_PATTERN, type OptionView } from '@/lib/advisor/options';

// Advisor v2: the capacity overview (DEC-1366), as GET /advisor-v2/capacity answers it. The two Needs attention
// lists are the shift lead's rules (lead_views.py): a stale figure shows no percentage and is never spare capacity.
// The five counts link to filtered lists under /advisor/v2/services. Pure.

export const V2_BROWSE_NOTE =
  'This page only looks services up. It opens no case and nothing is stored: not the postcode, the age or the needs.';

/** A named area of the organisation's patch (DEC-1375): its id, its name and the places it takes in. */
export type Area = { id: string; name: string; places: string };

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
  /** When the next report is due; when the service is out of hours, when it reopens. */
  nextDueAt: string | null;
  /** The postcode districts the service covers; none when none is recorded. */
  districts: string[];
  /** The one area the service is counted in: an area id (`network` for one that works across areas), or null when it
   *  is not placed. Always null when there is no area table. */
  area: string | null;
};
// The states the overview counts and lists (DEC-1381): the five, and Out of hours, so every service is in exactly one.
export type CountedStatus = 'accepting' | 'limited' | 'not-accepting' | 'over-capacity' | 'not-updated' | 'out-of-hours';
const zeroCounts = (): Record<CountedStatus, number> => ({
  accepting: 0,
  limited: 0,
  'not-accepting': 0,
  'over-capacity': 0,
  'not-updated': 0,
  'out-of-hours': 0,
});
export type Overview = {
  counts: Record<CountedStatus, number>;
  attentionShown: number;
  underPressure: PressureRow[];
  underutilised: SpareRow[];
  services: CapacityService[];
  /** The areas in display order. Empty when no area table is set up: the page then groups by postcode district. */
  areas: Area[];
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
  outOfHours: 'out-of-hours',
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

const AREA_ID = /^[a-z0-9][a-z0-9-]{0,39}$/;
const AREA_TEXT_MAX = 200;

function areaText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' && value.length <= AREA_TEXT_MAX ? value : null;
}

/** The areas, in the order given, each id once; anything not shaped like an area is dropped. No list is no areas. */
export function parseAreas(value: unknown): Area[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const areas: Area[] = [];
  for (const item of value) {
    if (!isRecord(item)) continue;
    const { id } = item;
    const name = areaText(item.name);
    const places = item.places === undefined ? '' : areaText(item.places);
    if (typeof id !== 'string' || !AREA_ID.test(id) || seen.has(id) || name === null || places === null) continue;
    seen.add(id);
    areas.push({ id, name, places });
  }
  return areas;
}

function serviceOf(value: unknown, areas: readonly Area[]): CapacityService | null {
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
    nextDueAt: str(value.nextDueAt),
    districts: Array.isArray(value.districts)
      ? value.districts.filter((item): item is string => typeof item === 'string' && DISTRICT_PATTERN.test(item))
      : [],
    // An area the list does not hold reads as not placed: a service is never counted under a card that is not there.
    area: typeof value.area === 'string' && areas.some((area) => area.id === value.area) ? value.area : null,
  };
}

function list<T>(value: unknown, read: (item: unknown) => T | null): T[] {
  return Array.isArray(value) ? value.map(read).filter((item): item is T => item !== null) : [];
}

/** The overview, or null when the answer is not shaped like one. */
export function parseOverview(body: unknown): Overview | null {
  if (!isRecord(body) || !isRecord(body.counts)) return null;
  const counts = zeroCounts();
  for (const [key, status] of Object.entries(COUNT_KEYS)) {
    // A back end that does not yet count Out of hours sends no such key: that is none, not a bad answer.
    const count = whole(body.counts[key]) ?? (status === 'out-of-hours' ? 0 : null);
    if (count === null) return null;
    counts[status] = count;
  }
  const areas = parseAreas(body.areas);
  return {
    counts,
    attentionShown: whole(body.attentionShown) ?? 3,
    underPressure: list(body.underPressure, pressureOf),
    underutilised: list(body.underutilised, spareOf),
    services: list(body.services, (item) => serviceOf(item, areas)),
    areas,
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
    nextDueAt: row.nextDueAt,
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

export const COUNTED_STATUSES: readonly CountedStatus[] = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated', 'out-of-hours'];

/** A service group's list under v2 (Capacity's group cards link here). */
export function groupHref(category: string): string {
  return `/advisor/v2/services?group=${encodeURIComponent(category)}`;
}

/** The group named in `?group=`, when it is shaped like a category code; anything else is ignored. */
export function groupFromQuery(value: string | string[] | undefined): string | null {
  const text = Array.isArray(value) ? (value[0] ?? '') : (value ?? '');
  return /^[a-z][a-z0-9-]{0,63}$/.test(text) ? text : null;
}

/** One entry per service group with its service count, by the group's name. */
export function groupsOfRows(rows: readonly CapacityService[]): { category: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const row of rows) counts.set(row.category, (counts.get(row.category) ?? 0) + 1);
  return [...counts.entries()].map(([category, count]) => ({ category, count })).sort((a, b) => a.category.localeCompare(b.category));
}

export type DistrictCard = { district: string | null; count: number; tally: Record<CountedStatus, number> };

/**
 * One card per postcode district, by district, with its services counted by state. A service that covers several
 * districts is counted in each; one with none recorded is under "Not placed" (district null), last. By name, never
 * by how many are accepting.
 */
export function districtCards(rows: readonly CapacityService[]): DistrictCard[] {
  const cards = new Map<string | null, DistrictCard>();
  const add = (district: string | null, row: CapacityService) => {
    const card = cards.get(district) ?? {
      district,
      count: 0,
      tally: zeroCounts(),
    };
    card.count += 1;
    if (row.status in card.tally) card.tally[row.status as CountedStatus] += 1;
    cards.set(district, card);
  };
  for (const row of rows) {
    if (row.districts.length === 0) add(null, row);
    for (const district of row.districts) add(district, row);
  }
  return [...cards.values()].sort((a, b) => (a.district === null ? 1 : b.district === null ? -1 : a.district.localeCompare(b.district)));
}

export type AreaCard = { area: string | null; name: string; places: string; count: number; tally: Record<CountedStatus, number> };

const emptyTally = zeroCounts;

/**
 * One card per area, in the order given (an empty area included), each service counted ONCE, in its own area; one with
 * no area is under "Not placed" (area null), last and only when there is one. So the cards add up to every service.
 * The area names arrive from the back end; none is written here.
 */
export function areaCards(rows: readonly CapacityService[], areas: readonly Area[]): AreaCard[] {
  const byId = new Map<string | null, AreaCard>(areas.map((area) => [area.id, { area: area.id, name: area.name, places: area.places, count: 0, tally: emptyTally() }]));
  const unplaced: AreaCard = { area: null, name: 'Not placed', places: 'No area recorded', count: 0, tally: emptyTally() };
  for (const row of rows) {
    const card = (row.area === null ? undefined : byId.get(row.area)) ?? unplaced;
    card.count += 1;
    if (row.status in card.tally) card.tally[row.status as CountedStatus] += 1;
  }
  return [...byId.values(), ...(unplaced.count > 0 ? [unplaced] : [])];
}

/** An area's list under v2; `none` is the services with no area. */
export function areaHref(area: string | null): string {
  return `/advisor/v2/services?area=${area === null ? 'none' : encodeURIComponent(area)}`;
}

/**
 * The area named in `?area=` (`none` for not placed), when it is shaped like an id and, if the areas are given, is one
 * of them; anything else is ignored (null). The server page checks the shape; the page that holds the areas checks the id.
 */
export function areaFromQuery(value: string | string[] | undefined, areas?: readonly Area[]): string | null {
  const text = Array.isArray(value) ? (value[0] ?? '') : (value ?? '');
  if (text === 'none') return text;
  if (!AREA_ID.test(text)) return null;
  return areas === undefined || areas.some((area) => area.id === text) ? text : null;
}

/** One card of Capacity's locations: an area when the organisation has areas, else a postcode district. */
export type LocationCard = { key: string; name: string; sub: string; href: string; count: number; tally: Record<CountedStatus, number> };

export function locationCards(overview: Pick<Overview, 'services' | 'areas'>): LocationCard[] {
  if (overview.areas.length > 0) {
    return areaCards(overview.services, overview.areas).map((card) => ({
      key: card.area ?? 'none',
      name: card.name,
      sub: card.places,
      href: areaHref(card.area),
      count: card.count,
      tally: card.tally,
    }));
  }
  return districtCards(overview.services).map((card) => ({
    key: card.district ?? 'none',
    name: card.district ?? 'Not placed',
    sub: card.district === null ? 'No district recorded' : 'Postcode district',
    href: districtHref(card.district),
    count: card.count,
    tally: card.tally,
  }));
}

/** A district's list under v2; `none` is the services with no district recorded. */
export function districtHref(district: string | null): string {
  return `/advisor/v2/services?district=${district === null ? 'none' : encodeURIComponent(district)}`;
}

/** The district named in `?district=` (`none` for not placed), when it is shaped like one; anything else is ignored. */
export function districtFromQuery(value: string | string[] | undefined): string | null {
  const text = Array.isArray(value) ? (value[0] ?? '') : (value ?? '');
  return text === 'none' || DISTRICT_PATTERN.test(text) ? text : null;
}
