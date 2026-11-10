import type { StatusCode } from '@/components/ui/StatusBadge';
import { LeadParseError, pressureList, underusedList } from '@/lib/lead/parse';
import type { AnalyticsArea, AnalyticsCounts, AnalyticsOverview, AnalyticsService } from './types';

// Reads the BFF's overview answer. A shape that is not the one the page knows is an error, never a partly filled
// page: an empty list would read as "nothing is under pressure" (H-330). Only the known fields are kept, so a field
// the back end should not send (a case, a postcode) is never passed on.

export class AnalyticsParseError extends Error {
  constructor() {
    super('The analytics overview could not be read.');
    this.name = 'AnalyticsParseError';
  }
}

const STATUSES: readonly StatusCode[] = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated', 'out-of-hours', 'last-known'];

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0) throw new AnalyticsParseError();
  return value;
}

function count(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) throw new AnalyticsParseError();
  return value;
}

function nullableCount(value: unknown): number | null {
  return value === null ? null : count(value);
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new AnalyticsParseError();
  return value;
}

// Area ids are short lower-case words with digits and hyphens; the name and the places line are plain text. Anything
// that is not shaped like that is dropped, never shown (DEC-1375).
const AREA_ID = /^[a-z0-9][a-z0-9-]{0,39}$/;
const AREA_TEXT_MAX = 200;

function areaText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' && value.length <= AREA_TEXT_MAX ? value : null;
}

/** The areas, in the order given, each id once. A missing list (a back end with no area table) is no areas. */
export function parseAreas(value: unknown): AnalyticsArea[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const areas: AnalyticsArea[] = [];
  for (const item of value) {
    if (!isObject(item)) continue;
    const { id, name } = item;
    const places = item.places === undefined ? '' : areaText(item.places);
    if (typeof id !== 'string' || !AREA_ID.test(id) || seen.has(id) || areaText(name) === null || places === null) continue;
    seen.add(id);
    areas.push({ id, name: name as string, places });
  }
  return areas;
}

function service(value: unknown, areas: readonly AnalyticsArea[]): AnalyticsService {
  if (!isObject(value) || typeof value.figureCurrent !== 'boolean') throw new AnalyticsParseError();
  const status = STATUSES.find((item) => item === value.status);
  if (status === undefined) throw new AnalyticsParseError();
  return {
    serviceId: text(value.serviceId),
    name: text(value.name),
    category: text(value.category),
    status,
    districts: list(value.districts).map(text),
    // An area the list does not hold reads as not placed: a service is never counted under a card that is not there.
    area: typeof value.area === 'string' && areas.some((area) => area.id === value.area) ? value.area : null,
    figureCurrent: value.figureCurrent,
    available: nullableCount(value.available),
    overBy: nullableCount(value.overBy),
    unitLabel: typeof value.unitLabel === 'string' ? value.unitLabel : '',
    reportedAt: value.reportedAt === null ? null : text(value.reportedAt),
  };
}

function counts(value: unknown): AnalyticsCounts {
  if (!isObject(value)) throw new AnalyticsParseError();
  return {
    accepting: count(value.accepting),
    limited: count(value.limited),
    notAccepting: count(value.notAccepting),
    overCapacity: count(value.overCapacity),
    notUpdated: count(value.notUpdated),
  };
}

export function parseAnalyticsOverview(value: unknown): AnalyticsOverview {
  if (!isObject(value)) throw new AnalyticsParseError();
  try {
    const areas = parseAreas(value.areas);
    return {
      generatedAt: text(value.generatedAt),
      counts: counts(value.counts),
      outOfHours: count(value.outOfHours),
      services: list(value.services).map((item) => service(item, areas)),
      areas,
      underPressure: pressureList(value.underPressure),
      underutilised: underusedList(value.underutilised),
    };
  } catch (error) {
    if (error instanceof LeadParseError) throw new AnalyticsParseError();
    throw error;
  }
}
