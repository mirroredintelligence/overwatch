// The BFF's reader of the add-a-service body (W18). It checks the shape before anything goes to the
// back end, and turns the checked body into the FHIR Parameters that $setup takes (DEC-652). An error
// names the field, never its value: a phone number or an email must not reach a log or a response.

import { FhirError } from '@/lib/fhir/client';
import { invalidRequest } from './bffInput';

/** A body the BFF refuses before it reaches the back end: a 400 with a fixed message. */
export class InvalidBody extends FhirError {
  constructor() {
    super(400, invalidRequest().outcome);
    this.name = 'InvalidBody';
  }
}

const CATEGORIES = [
  'urgent-community-response',
  'same-day-emergency-care',
  'inpatient-beds',
  'hospital-at-home-or-virtual-ward',
  'reablement',
  'urgent-treatment',
  'mental-health-crisis',
  'other',
] as const;
const MEASURES = ['free-slots', 'free-beds', 'referrals-acceptable', 'packages-free'] as const;
const CADENCES = ['every-2-hrs', 'twice-a-day', 'once-a-day'] as const;
const NEEDS = [
  'fall-no-injury',
  'frailty',
  'wound-care',
  'iv-therapy',
  'palliative',
  'dementia',
  'suspected-fracture',
  'head-injury-anticoagulants',
  'infection-isolation',
] as const;
const CHANNELS = ['text', 'email'] as const;
const CLOCK = /^([01]\d|2[0-3]):[0-5]\d$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DISTRICT = /^[A-Z]{1,2}[0-9][0-9A-Z]?$/;
const MOBILE = /^07\d{9}$/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_TEXT = 200;

export type ServiceBody = {
  name: string;
  category: (typeof CATEGORIES)[number];
  measure: (typeof MEASURES)[number];
  unitLabel: string;
  establishedCapacity: number;
  usualMin: number;
  usualMax: number;
  cadence: (typeof CADENCES)[number];
  channel: (typeof CHANNELS)[number];
  mobile?: string;
  email?: string;
  roleName: string;
  availableFrom: string;
  availableTo: string;
  ageMin: number;
  ageMax: number | null;
  districts: string[];
  accepts: string[];
  excludes: string[];
  reviewBy: string;
};

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new InvalidBody();
  return value as Record<string, unknown>;
}

function text(value: unknown, max = MAX_TEXT): string {
  if (typeof value !== 'string' || value.trim() === '' || value.length > max) throw new InvalidBody();
  return value.trim();
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): T {
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) throw new InvalidBody();
  return value as T;
}

function whole(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value > 100_000) {
    throw new InvalidBody();
  }
  return value;
}

function list<T extends string>(value: unknown, allowed: readonly T[]): T[] {
  if (!Array.isArray(value)) throw new InvalidBody();
  return value.map((item) => oneOf(item, allowed));
}

/** Reads and checks one add-a-service body. Throws InvalidBody, which names no value. */
export function readServiceBody(value: unknown): ServiceBody {
  const body = object(value);
  const channel = oneOf(body.channel, CHANNELS);
  const districts = Array.isArray(body.districts) ? body.districts.map((d) => text(d, 8)) : [];
  if (districts.length === 0) throw new InvalidBody();
  for (const district of districts) {
    if (!DISTRICT.test(district)) throw new InvalidBody();
  }
  const reviewBy = text(body.reviewBy, 10);
  if (!ISO_DATE.test(reviewBy)) throw new InvalidBody();
  const availableFrom = text(body.availableFrom, 5);
  const availableTo = text(body.availableTo, 5);
  if (!CLOCK.test(availableFrom) || !CLOCK.test(availableTo)) throw new InvalidBody();

  const result: ServiceBody = {
    name: text(body.name),
    category: oneOf(body.category, CATEGORIES),
    measure: oneOf(body.measure, MEASURES),
    unitLabel: text(body.unitLabel),
    establishedCapacity: whole(body.establishedCapacity),
    usualMin: whole(body.usualMin),
    usualMax: whole(body.usualMax),
    cadence: oneOf(body.cadence, CADENCES),
    channel,
    roleName: text(body.roleName),
    availableFrom,
    availableTo,
    ageMin: whole(body.ageMin),
    ageMax: body.ageMax === null || body.ageMax === undefined ? null : whole(body.ageMax),
    districts,
    accepts: list(body.accepts, NEEDS),
    excludes: list(body.excludes, NEEDS),
    reviewBy,
  };
  if (channel === 'text') {
    const mobile = text(body.mobile, 20);
    if (!MOBILE.test(mobile.replace(/\s/g, ''))) throw new InvalidBody();
    result.mobile = mobile;
  } else {
    const email = text(body.email, 254);
    if (!EMAIL.test(email)) throw new InvalidBody();
    result.email = email;
  }
  if (result.usualMax < result.usualMin) throw new InvalidBody();
  if (result.ageMax !== null && result.ageMax < result.ageMin) throw new InvalidBody();
  return result;
}

export type ParameterValue =
  | { name: string; valueString: string }
  | { name: string; valueCode: string }
  | { name: string; valueInteger: number }
  | { name: string; valueDate: string };

export type Parameters = { resourceType: 'Parameters'; parameter: ParameterValue[] };

/** The FHIR Parameters for $setup: one part per field, districts and needs repeated (R08). */
export function toParameters(body: ServiceBody): Parameters {
  const parts: ParameterValue[] = [
    { name: 'name', valueString: body.name },
    { name: 'category', valueCode: body.category },
    { name: 'measure', valueCode: body.measure },
    { name: 'unitLabel', valueString: body.unitLabel },
    { name: 'establishedCapacity', valueInteger: body.establishedCapacity },
    { name: 'usualMin', valueInteger: body.usualMin },
    { name: 'usualMax', valueInteger: body.usualMax },
    { name: 'cadence', valueCode: body.cadence },
    { name: 'channel', valueCode: body.channel },
    { name: 'roleName', valueString: body.roleName },
    { name: 'availableFrom', valueString: body.availableFrom },
    { name: 'availableTo', valueString: body.availableTo },
    { name: 'ageMin', valueInteger: body.ageMin },
    { name: 'reviewBy', valueDate: body.reviewBy },
  ];
  if (body.channel === 'text' && body.mobile !== undefined) {
    parts.push({ name: 'mobile', valueString: body.mobile });
  }
  if (body.channel === 'email' && body.email !== undefined) {
    parts.push({ name: 'email', valueString: body.email });
  }
  if (body.ageMax !== null) parts.push({ name: 'ageMax', valueInteger: body.ageMax });
  for (const district of body.districts) parts.push({ name: 'district', valueString: district });
  for (const need of body.accepts) parts.push({ name: 'accepts', valueCode: need });
  for (const need of body.excludes) parts.push({ name: 'excludes', valueCode: need });
  return { resourceType: 'Parameters', parameter: parts };
}

