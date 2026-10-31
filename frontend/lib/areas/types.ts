import { DISTRICT_PATTERN } from '@/lib/advisor/options';

// Coverage by postcode district (RadarWeb 4 and 5). THE BACK END DOES NOT OFFER THESE TWO ROUTES YET: this
// file is the contract the screens are built against (and the stand-in back end of the browser tests
// answers), written down so the back end task can match it. Nothing else is asked of the back end:
//
//   GET /planning/coverage?window=all|night|morning|afternoon|evening   (lead and executive)
//   GET /lead/services/{id}/coverage                                    (lead)
//   PUT /lead/services/{id}/coverage                                    (lead, Idempotency-Key)
//
// Areas are postcode districts or sectors, so they match how patients are placed (the design says so).

// ---- Coverage by time of day (RadarWeb 4) ----

export const WINDOWS = [
  { value: 'all', label: 'All day' },
  { value: 'night', label: '00:00 to 06:00' },
  { value: 'morning', label: '06:00 to 12:00' },
  { value: 'afternoon', label: '12:00 to 18:00' },
  { value: 'evening', label: '18:00 to 24:00' },
] as const;

export type WindowCode = (typeof WINDOWS)[number]['value'];

export function isWindow(value: string | null): value is WindowCode {
  return WINDOWS.some((item) => item.value === value);
}

export type DistrictCover = { district: string; services: string[] };

/** Referrals from districts nobody covers, over `days` days. A count under 10 is withheld (DEC-393). */
export type Uncovered = { count: number | null; suppressed: boolean; days: number };

export type CoverageView = { window: WindowCode; districts: DistrictCover[]; uncovered: Uncovered };

const MAX_DISTRICTS = 60;
const MAX_SERVICES = 20;
const MAX_NAME = 120;

function nameList(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > MAX_SERVICES) return null;
  const names: string[] = [];
  for (const item of value) {
    if (typeof item !== 'string' || item.length === 0 || item.length > MAX_NAME) return null;
    names.push(item);
  }
  return names;
}

/** The answer as the screen reads it, or null when it is not the shape above (never a guess). */
export function parseCoverage(value: unknown): CoverageView | null {
  if (typeof value !== 'object' || value === null) return null;
  const source = value as { window?: unknown; districts?: unknown; uncovered?: unknown };
  if (typeof source.window !== 'string' || !isWindow(source.window)) return null;
  if (!Array.isArray(source.districts) || source.districts.length > MAX_DISTRICTS) return null;
  const districts: DistrictCover[] = [];
  for (const item of source.districts) {
    const entry = item as { district?: unknown; services?: unknown } | null;
    const services = nameList(entry?.services);
    if (typeof entry?.district !== 'string' || !DISTRICT_PATTERN.test(entry.district) || services === null) return null;
    districts.push({ district: entry.district, services });
  }
  const uncovered = source.uncovered as { count?: unknown; suppressed?: unknown; days?: unknown } | null | undefined;
  if (uncovered === null || typeof uncovered !== 'object') return null;
  const suppressed = uncovered.suppressed === true;
  const count = typeof uncovered.count === 'number' && Number.isInteger(uncovered.count) && uncovered.count >= 0 ? uncovered.count : null;
  const days = typeof uncovered.days === 'number' && Number.isInteger(uncovered.days) && uncovered.days > 0 ? uncovered.days : null;
  // A count is either shown or withheld, never both and never neither.
  if (days === null || (suppressed ? count !== null : count === null)) return null;
  return { window: source.window, districts, uncovered: { count, suppressed, days } };
}

/** The districts with no visiting service, and those with two or more (in the order sent). */
export function summariseCoverage(view: CoverageView): { none: string[]; twoOrMore: string[] } {
  return {
    none: view.districts.filter((entry) => entry.services.length === 0).map((entry) => entry.district),
    twoOrMore: view.districts.filter((entry) => entry.services.length >= 2).map((entry) => entry.district),
  };
}

// ---- Define a coverage area (RadarWeb 5) ----

export const DAYS = [
  { value: 'mon', label: 'Mon' },
  { value: 'tue', label: 'Tue' },
  { value: 'wed', label: 'Wed' },
  { value: 'thu', label: 'Thu' },
  { value: 'fri', label: 'Fri' },
  { value: 'sat', label: 'Sat' },
  { value: 'sun', label: 'Sun' },
] as const;

export type DayCode = (typeof DAYS)[number]['value'];

/** Another service's cover of one of the districts on offer: what the overlap note names. */
export type OtherCover = { district: string; service: string };

export type CoverageForm = {
  serviceId: string;
  serviceName: string;
  /** The districts the organisation can choose from, in the order to show them. */
  available: string[];
  districts: string[];
  /** The response target in whole hours, or null when none is set yet. */
  responseHours: number | null;
  days: DayCode[];
  others: OtherCover[];
};

/** What a save sends: the three answers, nothing else (the service is the address). */
export type CoverageInput = { districts: string[]; responseHours: number; days: DayCode[] };

export const MAX_RESPONSE_HOURS = 72;

function isDay(value: unknown): value is DayCode {
  return DAYS.some((day) => day.value === value);
}

export function parseCoverageForm(value: unknown): CoverageForm | null {
  if (typeof value !== 'object' || value === null) return null;
  const source = value as Record<string, unknown>;
  const service = source.service as { id?: unknown; name?: unknown } | null | undefined;
  if (typeof service?.id !== 'string' || typeof service.name !== 'string' || service.name === '') return null;
  const districtList = (list: unknown): string[] | null => {
    if (!Array.isArray(list) || list.length > MAX_DISTRICTS) return null;
    const seen = new Set<string>();
    for (const item of list) {
      if (typeof item !== 'string' || !DISTRICT_PATTERN.test(item)) return null;
      seen.add(item);
    }
    return [...seen];
  };
  const available = districtList(source.available);
  const districts = districtList(source.districts);
  if (available === null || districts === null || !Array.isArray(source.days) || !source.days.every(isDay)) return null;
  const hours = source.responseHours;
  const responseHours = typeof hours === 'number' && Number.isInteger(hours) && hours >= 1 && hours <= MAX_RESPONSE_HOURS ? hours : null;
  const others: OtherCover[] = [];
  if (source.others !== undefined) {
    if (!Array.isArray(source.others) || source.others.length > MAX_DISTRICTS * MAX_SERVICES) return null;
    for (const item of source.others) {
      const entry = item as { district?: unknown; service?: unknown } | null;
      if (typeof entry?.district !== 'string' || !DISTRICT_PATTERN.test(entry.district) || typeof entry.service !== 'string' || entry.service === '') return null;
      others.push({ district: entry.district, service: entry.service });
    }
  }
  return {
    serviceId: service.id,
    serviceName: service.name,
    available,
    districts: districts.filter((district) => available.includes(district)),
    responseHours,
    days: [...new Set(source.days as DayCode[])],
    others,
  };
}

/**
 * The form as it goes over the wire, between the back end, the BFF and the browser: the shape
 * `parseCoverageForm` reads. The BFF sends on only what it read, so a field the screen does not show
 * does not pass through.
 */
export function coverageWire(form: CoverageForm) {
  return {
    service: { id: form.serviceId, name: form.serviceName },
    available: form.available,
    districts: form.districts,
    responseHours: form.responseHours,
    days: form.days,
    others: form.others,
  };
}

/** The overlap note's services: the others that already cover any of the chosen districts, once each. */
export function overlapWith(form: Pick<CoverageForm, 'others'>, chosen: readonly string[]): { service: string; districts: string[] }[] {
  const byService = new Map<string, string[]>();
  for (const entry of form.others) {
    if (!chosen.includes(entry.district)) continue;
    byService.set(entry.service, [...(byService.get(entry.service) ?? []), entry.district]);
  }
  return [...byService].map(([service, districts]) => ({ service, districts }));
}

export type CoverageProblem = 'districts' | 'hours' | 'days';

/** The first problem with a form, in the order the form reads, or null when it can be saved. */
export function problemsOf(draft: { districts: string[]; responseHours: string; days: DayCode[] }): CoverageProblem[] {
  const problems: CoverageProblem[] = [];
  if (draft.districts.length === 0) problems.push('districts');
  const hours = Number(draft.responseHours);
  if (!/^\d{1,2}$/.test(draft.responseHours.trim()) || hours < 1 || hours > MAX_RESPONSE_HOURS) problems.push('hours');
  if (draft.days.length === 0) problems.push('days');
  return problems;
}
