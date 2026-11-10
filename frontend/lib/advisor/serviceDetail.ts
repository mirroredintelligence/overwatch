import { STATUS_LABELS, type StatusCode } from '@/components/ui/StatusBadge';
import { NEEDS } from './codes';
import { PHONE_PATTERN, STALE_AFTER_SECONDS, type OptionView } from './options';

// The read behind the one service detail page (DEC-1367), as the browser holds it. Pure. The back end's answer is
// checked field by field, so a malformed answer is an error and never a drawn guess. Only the fields named here are
// kept: a person's email or mobile is not part of the answer and could not be shown if it were sent. What the system
// does not hold is null (or an empty list for districts) and the page leaves it out; nothing is made up.

export type OpeningWindow = { days: number[]; allDay: boolean; start: string | null; end: string | null };

export type ServiceDetailView = {
  serviceId: string;
  name: string;
  category: string | null;
  status: StatusCode;
  unitLabel: string;
  /** The normal capacity: the denominator of "Capacity remaining n / normal". */
  established: number;
  /** The places in use at the last report; null when not held. Shown only beside a current figure. */
  used: number | null;
  effectiveAvailable: number | null;
  overBy: number | null;
  lastFigure: number | null;
  reportedAt: string | null;
  nextDueAt: string | null;
  cadence: string | null;
  overdue: boolean;
  staleWarning: boolean;
  dataAgeSeconds: number | null;
  /** The service's own contact number (a role or switchboard number), or null when none is held. */
  phone: string | null;
  openingHours: OpeningWindow[];
  /** Need codes; null when the service has no current criteria (never an empty list that reads as "none"). */
  accepts: string[] | null;
  excludes: string[] | null;
  ageMin: number | null;
  ageMax: number | null;
  districts: string[];
};

export class ServiceDetailParseError extends Error {
  constructor() {
    super('The service detail is not in the shape the page knows.');
    this.name = 'ServiceDetailParseError';
  }
}

type Record_ = Record<string, unknown>;

const isObject = (value: unknown): value is Record_ => typeof value === 'object' && value !== null && !Array.isArray(value);
const fail = (): never => {
  throw new ServiceDetailParseError();
};
const text = (value: unknown): string => (typeof value === 'string' && value.trim() !== '' ? value : fail());
const nullableText = (value: unknown): string | null => (value === null || value === undefined ? null : text(value));
const whole = (value: unknown): number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : fail();
const nullableWhole = (value: unknown): number | null => (value === null || value === undefined ? null : whole(value));
const flag = (value: unknown): boolean => (typeof value === 'boolean' ? value : fail());
const instant = (value: unknown): string | null => {
  if (value === null || value === undefined) return null;
  return typeof value === 'string' && !Number.isNaN(Date.parse(value)) ? value : fail();
};
const textList = (value: unknown): string[] =>
  Array.isArray(value) ? value.map((item) => text(item)) : fail();
const nullableTextList = (value: unknown): string[] | null => (value === null || value === undefined ? null : textList(value));
const clock = (value: unknown): string | null => {
  if (value === null || value === undefined) return null;
  return typeof value === 'string' && /^\d{2}:\d{2}$/.test(value) ? value : fail();
};

/** A UK mobile (07..., +44 7...): a person's number, never a service's. The back end drops it too (DEC-1367). */
export function looksLikeMobile(number: string): boolean {
  let digits = number.replace(/\D/g, '');
  if (digits.startsWith('44')) digits = `0${digits.slice(2)}`;
  return /^07\d{9}$/.test(digits);
}

function status(value: unknown): StatusCode {
  return typeof value === 'string' && Object.hasOwn(STATUS_LABELS, value) ? (value as StatusCode) : fail();
}

function window_(value: unknown): OpeningWindow {
  if (!isObject(value) || !Array.isArray(value.days)) return fail();
  const days = value.days.map((day) => (typeof day === 'number' && Number.isInteger(day) && day >= 0 && day <= 6 ? day : fail()));
  return { days, allDay: flag(value.allDay), start: clock(value.start), end: clock(value.end) };
}

export function parseServiceDetail(value: unknown): ServiceDetailView {
  if (!isObject(value)) return fail();
  const phone = nullableText(value.phone);
  return {
    serviceId: text(value.serviceId),
    name: text(value.name),
    category: nullableText(value.category),
    status: status(value.status),
    unitLabel: text(value.unitLabel),
    established: whole(value.established),
    used: nullableWhole(value.used),
    effectiveAvailable: nullableWhole(value.effectiveAvailable),
    overBy: nullableWhole(value.overBy),
    lastFigure: nullableWhole(value.lastFigure),
    reportedAt: instant(value.reportedAt),
    nextDueAt: instant(value.nextDueAt),
    cadence: nullableText(value.cadence),
    overdue: flag(value.overdue),
    staleWarning: flag(value.staleWarning),
    dataAgeSeconds: nullableWhole(value.dataAgeSeconds),
    // A number that would not be offered as a phone link, or that is a personal mobile, is not offered at all.
    phone: phone !== null && PHONE_PATTERN.test(phone) && !looksLikeMobile(phone) ? phone : null,
    openingHours: Array.isArray(value.openingHours) ? value.openingHours.map(window_) : fail(),
    accepts: nullableTextList(value.accepts),
    excludes: nullableTextList(value.excludes),
    ageMin: nullableWhole(value.ageMin),
    ageMax: nullableWhole(value.ageMax),
    districts: textList(value.districts),
  };
}

/**
 * The detail as the card model the reporting helpers read (`reportingStrip`, `lastReportedLine`, `numberText`), so the page
 * and the advisor's cards agree on what is current. A late or old figure, or Not updated, is never the current capacity
 * (DEC-1343): the same four tests as the options list.
 */
export function detailAsOption(detail: ServiceDetailView): OptionView {
  return {
    serviceId: detail.serviceId,
    name: detail.name,
    category: detail.category,
    status: detail.status,
    effectiveAvailable: detail.effectiveAvailable,
    overBy: detail.overBy,
    unitLabel: detail.unitLabel,
    travelText: null,
    dataAgeSeconds: detail.dataAgeSeconds,
    staleWarning: detail.staleWarning,
    reportedAt: detail.reportedAt,
    nextDueAt: detail.nextDueAt,
    cadence: detail.cadence,
    lastFigure: detail.lastFigure,
    overdue: detail.overdue,
    figureUnavailable:
      detail.overdue ||
      detail.staleWarning ||
      detail.status === 'not-updated' ||
      (detail.dataAgeSeconds !== null && detail.dataAgeSeconds > STALE_AFTER_SECONDS),
    criteriaVersion: null,
    fits: [],
    checks: [],
    phone: detail.phone,
    network: null,
    position: null,
    coverage: null,
    travel: null,
  };
}

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function daysWords(days: number[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  if (sorted.length === 7) return 'Every day';
  const names = sorted.map((day) => DAY_NAMES[day] ?? '');
  const first = sorted[0] ?? 0;
  const last = sorted[sorted.length - 1] ?? 0;
  if (sorted.length >= 3 && last - first === sorted.length - 1) return `${names[0]} to ${names[names.length - 1]}`;
  if (names.length === 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/** One line per window: "Mon to Fri, 08:00 to 18:00", "Sat and Sun, all day". */
export function openingHoursLines(windows: OpeningWindow[]): string[] {
  return windows.map((window) => {
    const when = window.allDay || window.start === null || window.end === null ? 'all day' : `${window.start} to ${window.end}`;
    return `${daysWords(window.days)}, ${when}`;
  });
}

/** The labels of need codes; null when there are none held or a code the rules do not list (the page then says to phone). */
export function criteriaLabels(codes: string[] | null): string[] | null {
  if (codes === null) return null;
  const labels: string[] = [];
  for (const code of codes) {
    const need = NEEDS.find((item) => item.code === code);
    if (need === undefined) return null;
    labels.push(need.label);
  }
  return labels;
}

/** The districts the service covers, as one line; null when none are held. */
export function catchmentText(districts: string[]): string | null {
  return districts.length === 0 ? null : districts.join(', ');
}

/** "Age 18+" or "Age 18 to 65"; null when no age is held. */
export function ageText(min: number | null, max: number | null): string | null {
  if (min === null) return null;
  return max === null ? `Age ${min}+` : `Age ${min} to ${max}`;
}
