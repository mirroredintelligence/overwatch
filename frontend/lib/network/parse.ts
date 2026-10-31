import type {
  EndReason,
  NetworkBoard,
  NetworkBoardEntry,
  NetworkCriteria,
  NetworkCriteriaEntry,
  NetworkDirectory,
  NetworkDirectoryEntry,
  NetworkList,
  NetworkLocation,
  NetworkPhone,
  NetworkPhones,
  NetworkSummary,
  NetworkSystemNow,
  NetworkWeek,
  OpeningHour,
  Presentation,
  Pressure,
  SystemNowKey,
  WeekMeasure,
} from './types';
import { SYSTEM_NOW_KEYS, WEEK_PRESSURES, WEEK_STATUSES } from './types';
import type { BoardStatus } from '@/lib/board/types';

// Reads the network answers and fails closed (TEN-068). The same parser reads two shapes: the back end's
// own JSON (`backend`, snake_case: the BFF reads that) and the BFF's answer (`bff`, camelCase: the page
// reads that, and trusts the BFF no more than the BFF trusts the back end). It builds a new object from
// the fields it knows, so a field it does not know (a tenant id sent by mistake) never reaches a page,
// and a value it does not know is an error, never a guess. An error names the field only: never a value.

export class NetworkParseError extends Error {
  constructor(what: string) {
    super(`The network answer is not in the expected shape (${what}).`);
    this.name = 'NetworkParseError';
  }
}

export type KeyStyle = 'backend' | 'bff';

const CATEGORIES: readonly string[] = [
  'urgent-community-response',
  'same-day-emergency-care',
  'inpatient-beds',
  'hospital-at-home-or-virtual-ward',
  'reablement',
  'urgent-treatment',
  'mental-health-crisis',
  'other',
];
const NEEDS: readonly string[] = [
  'fall-no-injury',
  'frailty',
  'wound-care',
  'iv-therapy',
  'palliative',
  'dementia',
  'suspected-fracture',
  'head-injury-anticoagulants',
  'infection-isolation',
];
const STATUSES: readonly BoardStatus[] = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated', 'out-of-hours'];
const PRESENTATIONS: readonly Presentation[] = ['shown', 'unavailable'];
const PRESSURES: readonly Pressure[] = ['normal', 'watch', 'high'];
const END_REASONS: readonly EndReason[] = ['left', 'grant-ended', 'replaced'];
const SOURCES = ['manual', 'directory-of-services'] as const;
const NETWORK_ID = /^net-[a-z0-9][a-z0-9-]{1,26}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const TIME_OF_DAY = /^\d{2}:\d{2}$/;
const MAX_TEXT = 200;

function fail(what: string): never {
  throw new NetworkParseError(what);
}

function snake(key: string): string {
  return key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
}

/** One object being read, with the names of its fields in the style it came in. */
class Shape {
  constructor(
    private readonly source: Record<string, unknown>,
    private readonly style: KeyStyle,
    private readonly where: string,
  ) {}

  static of(value: unknown, style: KeyStyle, where: string): Shape {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) fail(`${where} is not an object`);
    return new Shape(value as Record<string, unknown>, style, where);
  }

  private raw(key: string): unknown {
    return this.source[this.style === 'backend' ? snake(key) : key];
  }

  /** Where this object is, for an error. */
  get label(): string {
    return this.where;
  }

  /** The value of a field as it came, for a check of whether it is there at all. */
  rawValue(key: string): unknown {
    return this.raw(key);
  }

  private name(key: string): string {
    return `${this.where}.${key}`;
  }

  text(key: string): string {
    const value = this.raw(key);
    if (typeof value !== 'string' || value.length > MAX_TEXT) fail(`${this.name(key)} is missing or not text`);
    return value;
  }

  nullableText(key: string): string | null {
    return this.raw(key) === null ? null : this.text(key);
  }

  oneOf<T extends string>(key: string, allowed: readonly T[]): T {
    const value = this.raw(key);
    if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) fail(`${this.name(key)} is not a known value`);
    return value as T;
  }

  nullableOneOf<T extends string>(key: string, allowed: readonly T[]): T | null {
    return this.raw(key) === null ? null : this.oneOf(key, allowed);
  }

  bool(key: string): boolean {
    const value = this.raw(key);
    if (typeof value !== 'boolean') fail(`${this.name(key)} is missing or not true or false`);
    return value;
  }

  count(key: string): number {
    const value = this.raw(key);
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) fail(`${this.name(key)} is missing or not a count`);
    return value;
  }

  nullableCount(key: string): number | null {
    return this.raw(key) === null ? null : this.count(key);
  }

  nullableNumber(key: string): number | null {
    const value = this.raw(key);
    if (value === null) return null;
    if (typeof value !== 'number' || !Number.isFinite(value)) fail(`${this.name(key)} is not a number`);
    return value;
  }

  instant(key: string): string {
    const value = this.raw(key);
    if (typeof value !== 'string' || Number.isNaN(Date.parse(value))) fail(`${this.name(key)} is missing or not a time`);
    return value;
  }

  nullableInstant(key: string): string | null {
    return this.raw(key) === null ? null : this.instant(key);
  }

  date(key: string): string {
    const value = this.raw(key);
    if (typeof value !== 'string' || !DATE.test(value) || Number.isNaN(Date.parse(value))) fail(`${this.name(key)} is missing or not a date`);
    return value;
  }

  nullableTimeOfDay(key: string): string | null {
    const value = this.raw(key);
    if (value === null) return null;
    if (typeof value !== 'string' || !TIME_OF_DAY.test(value)) fail(`${this.name(key)} is not a time of day`);
    return value;
  }

  list<T>(key: string, read: (item: unknown, index: number) => T): T[] {
    const value = this.raw(key);
    if (!Array.isArray(value)) fail(`${this.name(key)} is missing or not a list`);
    return value.map((item, index) => read(item, index));
  }

  textList(key: string, allowed?: readonly string[]): string[] {
    return this.list(key, (item) => {
      if (typeof item !== 'string' || item.length > MAX_TEXT || (allowed !== undefined && !allowed.includes(item))) fail(`${this.name(key)} holds a value that is not allowed`);
      return item;
    });
  }

  child(key: string): Shape {
    return Shape.of(this.raw(key), this.style, this.name(key));
  }

  /** An object whose keys are data (status words), read key by key. */
  keyed<T>(key: string, keys: readonly string[], read: (shape: Shape, name: string) => T): Record<string, T> {
    const inner = this.child(key);
    const out: Record<string, T> = {};
    for (const name of keys) out[name] = read(inner.dataKey(name), name);
    return out;
  }

  /** A shape whose fields are read under one data key, in the same style. */
  dataKey(name: string): Shape {
    return Shape.of(this.source[name], this.style, `${this.where}.${name}`);
  }

  countAt(name: string): number {
    const value = this.source[name];
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) fail(`${this.where}.${name} is missing or not a count`);
    return value;
  }
}

function header(shape: Shape) {
  return { systemName: shape.text('systemName'), pathwayName: shape.text('pathwayName'), timeZone: shape.text('timeZone') };
}

function networkId(shape: Shape, key: string): string {
  const id = shape.text(key);
  if (!NETWORK_ID.test(id)) fail(`${shape.label}.${key} is not a network id`);
  return id;
}

export function parseNetworks(body: unknown, style: KeyStyle): NetworkSummary[] {
  return Shape.of(body, style, 'networks').list('networks', (item) => {
    const shape = Shape.of(item, style, 'network');
    return {
      id: networkId(shape, 'id'),
      name: shape.text('name'),
      systemName: shape.text('systemName'),
      pathwayName: shape.text('pathwayName'),
      timeZone: shape.text('timeZone'),
    };
  });
}

/** The BFF's answer to `GET /api/bff/network`: the viewer's own organisation and the networks it may see. */
export function parseNetworkList(body: unknown): NetworkList {
  const shape = Shape.of(body, 'bff', 'networkList');
  return { ownOrganisation: shape.nullableText('ownOrganisation'), networks: parseNetworks(body, 'bff') };
}

function boardEntry(item: unknown, style: KeyStyle): NetworkBoardEntry {
  const shape = Shape.of(item, style, 'entry');
  return {
    rowRef: shape.text('rowRef'),
    organisationName: shape.text('organisationName'),
    serviceName: shape.text('serviceName'),
    category: shape.oneOf('category', CATEGORIES),
    presentation: shape.oneOf('presentation', PRESENTATIONS),
    status: shape.nullableOneOf('status', STATUSES),
    unitLabel: shape.nullableText('unitLabel'),
    effectiveAvailable: shape.nullableCount('effectiveAvailable'),
    overBy: shape.nullableCount('overBy'),
    used: shape.nullableCount('used'),
    established: shape.nullableCount('established'),
    reportedAt: shape.nullableInstant('reportedAt'),
    staleWarning: shape.bool('staleWarning'),
    wasDueAt: shape.nullableInstant('wasDueAt'),
  };
}

export function parseBoard(body: unknown, style: KeyStyle): NetworkBoard {
  const shape = Shape.of(body, style, 'board');
  return {
    entries: shape.list('entries', (item) => boardEntry(item, style)),
    pressure: shape.oneOf('pressure', PRESSURES),
    allLimitedOrWorse: shape.bool('allLimitedOrWorse'),
    generatedAt: shape.instant('generatedAt'),
    ...header(shape),
  };
}

function openingHour(item: unknown, style: KeyStyle): OpeningHour {
  const shape = Shape.of(item, style, 'openingHour');
  const days = shape.list('days', (day) => {
    if (typeof day !== 'number' || !Number.isInteger(day) || day < 0 || day > 6) fail('openingHour.days holds a value that is not a day');
    return day;
  });
  if (days.length === 0) fail('openingHour.days is empty');
  return {
    position: shape.count('position'),
    days,
    allDay: shape.bool('allDay'),
    start: shape.nullableTimeOfDay('start'),
    end: shape.nullableTimeOfDay('end'),
  };
}

function directoryEntry(item: unknown, style: KeyStyle): NetworkDirectoryEntry {
  const shape = Shape.of(item, style, 'entry');
  let where: NetworkLocation | null = null;
  if (shape.rawValue('location') !== null) {
    const loc = shape.child('location');
    where = {
      name: loc.text(style === 'backend' ? 'locationName' : 'name'),
      postalDistrict: loc.text('postalDistrict'),
      city: loc.text('city'),
      latitude: loc.nullableNumber('latitude'),
      longitude: loc.nullableNumber('longitude'),
    };
  }
  return {
    rowRef: shape.text('rowRef'),
    organisationName: shape.text('organisationName'),
    serviceName: shape.text('serviceName'),
    category: shape.oneOf('category', CATEGORIES),
    active: shape.bool('active'),
    source: shape.oneOf('source', SOURCES),
    contactLabel: shape.nullableText('contactLabel'),
    contactPhone: shape.nullableText('contactPhone'),
    location: where,
    openingHours: shape.list('openingHours', (hour) => openingHour(hour, style)),
    presentation: shape.oneOf('presentation', PRESENTATIONS),
    endedAt: shape.nullableInstant('endedAt'),
    endReason: shape.nullableOneOf('endReason', END_REASONS),
  };
}

export function parseDirectory(body: unknown, style: KeyStyle): NetworkDirectory {
  const shape = Shape.of(body, style, 'directory');
  return { entries: shape.list('entries', (item) => directoryEntry(item, style)), ...header(shape) };
}

function criteriaEntry(item: unknown, style: KeyStyle): NetworkCriteriaEntry {
  const shape = Shape.of(item, style, 'entry');
  return {
    rowRef: shape.text('rowRef'),
    organisationName: shape.text('organisationName'),
    serviceName: shape.text('serviceName'),
    version: shape.count('version'),
    ageMin: shape.count('ageMin'),
    ageMax: shape.count('ageMax'),
    districts: shape.textList('districts'),
    accepts: shape.textList('accepts', NEEDS),
    excludes: shape.textList('excludes', NEEDS),
    reviewBy: shape.date('reviewBy'),
    endedAt: shape.nullableInstant('endedAt'),
    endReason: shape.nullableOneOf('endReason', END_REASONS),
  };
}

export function parseCriteria(body: unknown, style: KeyStyle): NetworkCriteria {
  const shape = Shape.of(body, style, 'criteria');
  return { entries: shape.list('entries', (item) => criteriaEntry(item, style)), ...header(shape) };
}

export function parseSystemNow(body: unknown, style: KeyStyle): NetworkSystemNow {
  const shape = Shape.of(body, style, 'systemNow');
  const counts = shape.child('byStatus');
  const byStatus = {} as Record<SystemNowKey, number>;
  for (const key of SYSTEM_NOW_KEYS) byStatus[key] = counts.countAt(key);
  const alert = shape.child('alert');
  return {
    generatedAt: shape.instant('generatedAt'),
    services: shape.count('services'),
    organisations: shape.count('organisations'),
    byStatus,
    pressure: shape.oneOf('pressure', PRESSURES),
    allLimitedOrWorse: shape.bool('allLimitedOrWorse'),
    alert: {
      raised: alert.bool('raised'),
      level: alert.oneOf('level', PRESSURES),
      limitedOrWorse: alert.count('limitedOrWorse'),
      watchFrom: alert.count('watchFrom'),
      highFrom: alert.count('highFrom'),
    },
    ...header(shape),
  };
}

function phone(item: unknown, style: KeyStyle): NetworkPhone {
  const shape = Shape.of(item, style, 'phone');
  return {
    rowRef: shape.text('rowRef'),
    organisationName: shape.text('organisationName'),
    serviceName: shape.text('serviceName'),
    category: shape.oneOf('category', CATEGORIES),
    presentation: shape.oneOf('presentation', PRESENTATIONS),
    status: shape.nullableOneOf('status', STATUSES),
    staleWarning: shape.bool('staleWarning'),
    reportedAt: shape.nullableInstant('reportedAt'),
    contactLabel: shape.nullableText('contactLabel'),
    contactPhone: shape.nullableText('contactPhone'),
  };
}

export function parsePhones(body: unknown, style: KeyStyle): NetworkPhones {
  const shape = Shape.of(body, style, 'phones');
  return {
    phones: shape.list('phones', (item) => phone(item, style)),
    organisations: shape.count('organisations'),
    ...header(shape),
  };
}

function measure(shape: Shape): WeekMeasure {
  const value = shape.nullableNumber('value');
  const hidden = shape.bool('hidden');
  // A hidden figure carries no value, and a figure that is shown carries one.
  if (hidden !== (value === null)) fail(`${shape.label} hides a value or shows none`);
  return { label: shape.text('label'), value, hidden };
}

export function parseWeek(body: unknown, style: KeyStyle): NetworkWeek {
  const shape = Shape.of(body, style, 'week');
  const statusShare = shape.keyed('statusShare', WEEK_STATUSES, (inner) => measure(inner));
  const pressureHours = shape.keyed('pressureHours', WEEK_PRESSURES, (inner) => measure(inner));
  return {
    weekStart: shape.date('weekStart'),
    withheld: shape.bool('withheld'),
    hoursSampled: measure(shape.child('hoursSampled')),
    onTimePct: measure(shape.child('onTimePct')),
    statusShare: statusShare as NetworkWeek['statusShare'],
    pressureHours: pressureHours as NetworkWeek['pressureHours'],
    pressureOverTime: shape.list('pressureOverTime', (item) => {
      const point = Shape.of(item, style, 'point');
      return { hour: point.instant('hour'), pressure: point.oneOf('pressure', PRESSURES) };
    }),
    ...header(shape),
  };
}
