import type { StatusCode } from '@/components/ui/StatusBadge';
import type { LatLon } from '@/lib/map/project';

// The options of a case as the browser reads them (W13): the back end's `$filter-options` Parameters
// (routes_cases.py `_filter_to_fhir`) turned into plain data. Pure. Only the parts named here are
// read; anything else in the answer is dropped, so no field the browser does not show can reach it.
// A status the rules do not know is shown as Not updated, never as accepting.

/** Data older than this is flagged: "Data is over 2 hrs old. Consider phoning." (W13). */
export const STALE_AFTER_SECONDS = 2 * 60 * 60;

const KNOWN_STATUS: readonly StatusCode[] = [
  'accepting',
  'limited',
  'not-accepting',
  'over-capacity',
  'not-updated',
  'out-of-hours',
];

/** The organisation that owns a network service, and where its figures come from (network-ui.md). */
export type NetworkTag = { organisation: string; source: string };

/** One leg of a travel estimate: a range in minutes, how it was measured, and its source (W50). */
export type TravelLeg = { label: string; low: number; high: number; how: string; source: string };
export type Travel = { low: number; high: number; source: string; legs: TravelLeg[] };
/** A visiting service's coverage: a circle around its base, in kilometres. */
export type Coverage = LatLon & { radiusKm: number };

export type OptionView = {
  serviceId: string;
  name: string;
  category: string | null;
  status: StatusCode;
  effectiveAvailable: number | null;
  overBy: number | null;
  unitLabel: string | null;
  travelText: string | null;
  dataAgeSeconds: number | null;
  staleWarning: boolean;
  criteriaVersion: number | null;
  fits: string[];
  checks: string[];
  phone: string | null;
  /** Null for the viewer's own organisation. */
  network: NetworkTag | null;
  /** A fixed site's place on the map (W50). Null for a visiting service and when none was sent. */
  position: LatLon | null;
  /** A visiting service's area (W50). Null for a fixed site. */
  coverage: Coverage | null;
  /** The travel estimate from the patient (W50). Null when no range was sent. */
  travel: Travel | null;
};

export type NotSuitableView = { serviceId: string; name: string; reason: string };

export type OptionsParts = {
  options: OptionView[];
  notSuitable: NotSuitableView[];
  /** The patient's point, from the postcode centre (W50). Null when none was sent. */
  patientArea: LatLon | null;
  /** The postcode is not found: the map shows the not-found state (W50). */
  notFound: boolean;
  /** The postcode is outside the areas the services cover (W50). */
  outOfArea: boolean;
  /**
   * The districts the advisor can choose from when the postcode was not found or is outside the area
   * (W50, W9H DEC-1045): the ones the services cover, in the order to show them. Empty otherwise.
   */
  districts: string[];
  /**
   * What the BFF says of the other organisations' services (B6): none (no network), shown (read and
   * added after the viewer's own, each with its organisation), or unavailable (they could not be read:
   * the screen says so). Set by the BFF, never by the back end's answer.
   */
  network?: NetworkRead;
};

export type NetworkRead = 'none' | 'shown' | 'unavailable';

/**
 * A number the screen offers to phone: digits with spaces, brackets and dashes, and an optional leading
 * plus, five to twenty-five characters. Anything else is not offered (it would become a phone link).
 */
export const PHONE_PATTERN = /^\+?[0-9][0-9 ()-]{4,24}$/;

/** A postcode district as the back end keeps it: one or two capital letters, a digit, then a digit or a capital. */
export const DISTRICT_PATTERN = /^[A-Z]{1,2}[0-9][A-Z0-9]?$/;
/** At most this many chips (the back end sends twelve at most). */
export const MAX_DISTRICT_CHIPS = 12;

type Part = {
  name?: unknown;
  valueString?: unknown;
  valueCode?: unknown;
  valueInteger?: unknown;
  valueDecimal?: unknown;
  valueBoolean?: unknown;
  part?: unknown;
};

const asParts = (value: unknown): Part[] => (Array.isArray(value) ? (value as Part[]) : []);

function text(parts: Part[], name: string): string | null {
  const found = parts.find((part) => part.name === name);
  if (typeof found?.valueString === 'string') return found.valueString;
  if (typeof found?.valueCode === 'string') return found.valueCode;
  return null;
}

function whole(parts: Part[], name: string): number | null {
  const found = parts.find((part) => part.name === name);
  return typeof found?.valueInteger === 'number' && Number.isInteger(found.valueInteger) ? found.valueInteger : null;
}

function list(parts: Part[], name: string): string[] {
  return parts
    .filter((part) => part.name === name && typeof part.valueString === 'string')
    .map((part) => part.valueString as string);
}

function decimal(parts: Part[], name: string): number | null {
  const found = parts.find((part) => part.name === name);
  return typeof found?.valueDecimal === 'number' && Number.isFinite(found.valueDecimal) ? found.valueDecimal : null;
}

function flag(parts: Part[], name: string): boolean {
  return parts.find((part) => part.name === name)?.valueBoolean === true;
}

/** A place on the earth, or null when the numbers cannot be one (a coordinate out of range is refused). */
function placeOf(lat: number | null, lon: number | null): LatLon | null {
  if (lat === null || lon === null) return null;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

function legsOf(parts: Part[]): TravelLeg[] {
  const legs: TravelLeg[] = [];
  for (const item of parts) {
    if (item.name !== 'leg') continue;
    const inner = asParts(item.part);
    const label = text(inner, 'label');
    const low = whole(inner, 'low');
    const high = whole(inner, 'high');
    if (label === null || low === null || high === null) continue;
    legs.push({
      label,
      low,
      high,
      how: text(inner, 'how') ?? '',
      source: text(inner, 'source') ?? '',
    });
  }
  return legs;
}

function travelText(low: number | null, high: number | null): string | null {
  if (low === null || high === null) return null;
  return low === high ? `about ${low} min` : `about ${low} to ${high} min`;
}

/** The service's number when it is shaped like one, else none: never a guess, never text of another kind. */
function phoneOf(value: string | null): string | null {
  return value !== null && PHONE_PATTERN.test(value) ? value : null;
}

function optionOf(parts: Part[]): OptionView | null {
  const serviceId = text(parts, 'serviceId');
  const name = text(parts, 'name');
  if (serviceId === null || name === null) return null;
  const rawStatus = text(parts, 'status');
  const status: StatusCode =
    rawStatus !== null && (KNOWN_STATUS as readonly string[]).includes(rawStatus)
      ? (rawStatus as StatusCode)
      : 'not-updated';
  const dataAgeSeconds = whole(parts, 'dataAgeSeconds');
  const low = whole(parts, 'travelLow');
  const high = whole(parts, 'travelHigh');
  const place = placeOf(decimal(parts, 'lat'), decimal(parts, 'lon'));
  const radiusKm = decimal(parts, 'coverageRadiusKm');
  const organisation = text(parts, 'organisation');
  // A visiting service has a coverage area and no fixed place; a fixed site has a place.
  const coverage = radiusKm !== null && place !== null && radiusKm > 0 ? { ...place, radiusKm } : null;
  return {
    serviceId,
    name,
    category: text(parts, 'category'),
    status,
    effectiveAvailable: whole(parts, 'effectiveAvailable'),
    overBy: whole(parts, 'overBy'),
    unitLabel: text(parts, 'unitLabel'),
    travelText: travelText(low, high),
    dataAgeSeconds,
    staleWarning: dataAgeSeconds !== null && dataAgeSeconds > STALE_AFTER_SECONDS,
    criteriaVersion: whole(parts, 'criteriaVersion'),
    fits: list(parts, 'fits'),
    checks: list(parts, 'checks'),
    phone: phoneOf(text(parts, 'phone')),
    network:
      organisation === null ? null : { organisation, source: text(parts, 'organisationSource') ?? '' },
    position: coverage === null ? place : null,
    coverage,
    travel: low !== null && high !== null ? { low, high, source: text(parts, 'travelSource') ?? '', legs: legsOf(parts) } : null,
  };
}

/**
 * The options and the not-suitable list, in the order the back end sent them. Null when the answer
 * is not a Parameters resource, so the route can answer 502 rather than show a guess.
 */
export function optionsFromParameters(value: unknown): OptionsParts | null {
  if (typeof value !== 'object' || value === null) return null;
  const resource = value as { resourceType?: unknown; parameter?: unknown };
  if (resource.resourceType !== 'Parameters') return null;

  const options: OptionView[] = [];
  const notSuitable: NotSuitableView[] = [];
  const top = asParts(resource.parameter);
  const patientArea = placeOf(
    decimal(top, 'patientLat'),
    decimal(top, 'patientLon'),
  );
  for (const item of top) {
    const parts = asParts(item.part);
    if (item.name === 'option') {
      const option = optionOf(parts);
      if (option !== null) options.push(option);
    } else if (item.name === 'notSuitable') {
      const serviceId = text(parts, 'serviceId');
      const name = text(parts, 'name');
      const reason = text(parts, 'reason');
      if (serviceId !== null && name !== null && reason !== null) notSuitable.push({ serviceId, name, reason });
    }
  }
  const notFound = flag(top, 'notFound');
  const outOfArea = flag(top, 'outOfArea');
  return {
    options,
    notSuitable,
    patientArea,
    notFound,
    outOfArea,
    districts: notFound || outOfArea ? districtsOf(top) : [],
  };
}

/** The `district` parts in the order sent: only what is a district, once each, at most the chips the screen shows. */
function districtsOf(top: Part[]): string[] {
  const seen = new Set<string>();
  for (const part of top) {
    if (part.name !== 'district') continue;
    const value = part.valueString;
    if (typeof value === 'string' && DISTRICT_PATTERN.test(value)) seen.add(value);
    if (seen.size === MAX_DISTRICT_CHIPS) break;
  }
  return [...seen];
}
