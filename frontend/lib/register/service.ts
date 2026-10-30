// The service step's checks and mapping (W25). Pure: the browser and the BFF both use it. The
// criteria set here are what advisors filter on, so each code is checked against the back end's
// own list before it is sent, and a value the list does not hold is refused, never passed on.

import { DAY_OPTIONS, EXCLUDED_NEED_OPTIONS, NEED_OPTIONS, REFERRAL_METHODS, SERVICE_CATEGORIES } from './options';
import type { FieldIssue } from './types';

export type ServiceAnswers = {
  category?: string;
  referralMethods?: string[];
  spoaPhone?: string;
  acceptingDays?: string[];
  acceptingStart?: string;
  acceptingEnd?: string;
  needs?: string[];
  ageMin?: string;
  /** The oldest age as text, or null for "No limit". */
  ageMax?: string | null;
  excludedNeeds?: string[];
  noExclusions?: boolean;
  ownerRole?: string;
  ownerEmail?: string;
  reviewBy?: string;
  districts?: string[];
};

export type ServiceContext = { fixedSite: boolean | undefined; today: string };

const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const DISTRICT = /^[A-Z]{1,2}\d[A-Z\d]?$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const AGE_MIN = 0;
const AGE_MAX = 120;

const values = (options: readonly { value: string }[]) => options.map((option) => option.value);
const CATEGORY_CODES = values(SERVICE_CATEGORIES);
const REFERRAL_CODES = values(REFERRAL_METHODS);
const DAY_CODES = values(DAY_OPTIONS);
const NEED_CODES = values(NEED_OPTIONS);
const EXCLUDED_CODES = values(EXCLUDED_NEED_OPTIONS);

function blank(value: string | undefined): boolean {
  return value === undefined || value.trim() === '';
}

function allIn(list: readonly string[] | undefined, allowed: readonly string[]): boolean {
  return (list ?? []).every((item) => allowed.includes(item));
}

/** A district as `DT5`, from any case, or null. A bare area (`DT`) or a full postcode is not one. */
export function normaliseDistrict(input: string): string | null {
  const text = input.trim().toUpperCase();
  return DISTRICT.test(text) ? text : null;
}

/** A whole number of years in text, or null. */
function whole(text: string | undefined): number | null {
  if (text === undefined || !/^\d{1,3}$/.test(text.trim())) return null;
  return Number(text.trim());
}

function timeOk(text: string | undefined): boolean {
  return text !== undefined && TIME.test(text);
}

/** A full UK number: 10 or 11 digits starting 0, spaces and hyphens not counted. */
function ukPhone(text: string): boolean {
  return /^0\d{9,10}$/.test(text.replace(/[\s-]/g, ''));
}

export function validateService(answers: ServiceAnswers, context: ServiceContext): FieldIssue[] {
  const issues: FieldIssue[] = [];
  if (answers.category === undefined || !CATEGORY_CODES.includes(answers.category)) {
    issues.push({ field: 'category', message: 'Choose a category' });
  }
  if ((answers.referralMethods ?? []).length === 0) {
    issues.push({ field: 'referralMethods', message: 'Choose how the coordination team can refer' });
  }
  const phone = answers.spoaPhone ?? '';
  if (blank(phone)) {
    issues.push({ field: 'spoaPhone', message: 'Enter a phone number the coordination team can call' });
  } else if (!ukPhone(phone)) {
    issues.push({ field: 'spoaPhone', message: 'Enter a full phone number, for example 01632 960123' });
  }
  if ((answers.acceptingDays ?? []).length === 0) {
    issues.push({ field: 'acceptingDays', message: 'Choose the days you accept referrals' });
  }
  if (!timeOk(answers.acceptingStart)) issues.push({ field: 'acceptingStart', message: 'Enter a time like 08:00' });
  if (!timeOk(answers.acceptingEnd)) issues.push({ field: 'acceptingEnd', message: 'Enter a time like 08:00' });
  if ((answers.needs ?? []).length === 0) {
    issues.push({ field: 'needs', message: 'Choose at least one need you accept' });
  }

  const youngest = whole(answers.ageMin);
  if (youngest === null || youngest < AGE_MIN || youngest > AGE_MAX) {
    issues.push({ field: 'ageMin', message: 'Enter the youngest age, from 0 to 120' });
  }
  if (answers.ageMax !== null) {
    const oldest = whole(answers.ageMax);
    if (oldest === null || oldest > AGE_MAX) {
      issues.push({ field: 'ageMax', message: 'Enter the oldest age, or choose no limit' });
    } else if (youngest !== null && oldest < youngest) {
      issues.push({ field: 'ageMax', message: 'Oldest age must be at least the youngest age' });
    }
  }

  if (!answers.noExclusions && (answers.excludedNeeds ?? []).length === 0) {
    issues.push({ field: 'excludedNeeds', message: 'Choose the needs you do not accept, or No exclusions' });
  }
  if (blank(answers.ownerRole)) issues.push({ field: 'ownerRole', message: 'Enter who owns the criteria' });
  if (!EMAIL.test((answers.ownerEmail ?? '').trim())) {
    issues.push({ field: 'ownerEmail', message: "Enter the owner's email address" });
  }
  const review = answers.reviewBy ?? '';
  if (!ISO_DATE.test(review) || review <= context.today) {
    issues.push({ field: 'reviewBy', message: 'Enter a review date in the future' });
  }
  if (context.fixedSite === false && (answers.districts ?? []).length === 0) {
    issues.push({ field: 'districts', message: 'Choose the districts you cover' });
  }
  return issues;
}

/**
 * The service step's values as the back end takes them (R10 ServiceStep). Returns null when a code
 * or a district is not one the back end holds, so the route refuses the save with a 400.
 */
export function serviceValues(body: Record<string, unknown>, serviceName: string): Record<string, unknown> | null {
  const out: Record<string, unknown> = { serviceName };
  const list = (key: string): string[] | undefined => {
    const value = body[key];
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : undefined;
  };

  if (body.category !== undefined) {
    if (typeof body.category !== 'string' || !CATEGORY_CODES.includes(body.category)) return null;
    out.category = body.category;
  }
  const referrals = list('referralMethods');
  if (referrals !== undefined) {
    if (!allIn(referrals, REFERRAL_CODES)) return null;
    out.referralMethods = referrals.join(',');
  }
  if (typeof body.spoaPhone === 'string') out.spoaPhone = body.spoaPhone;
  const days = list('acceptingDays');
  if (days !== undefined) {
    if (!allIn(days, DAY_CODES)) return null;
    out.acceptingDays = days.join(',');
  }
  if (typeof body.acceptingStart === 'string') out.acceptingStart = body.acceptingStart;
  if (typeof body.acceptingEnd === 'string') out.acceptingEnd = body.acceptingEnd;
  const needs = list('needs');
  if (needs !== undefined) {
    if (!allIn(needs, NEED_CODES)) return null;
    out.needs = needs.join(',');
  }
  if (typeof body.ageMin === 'number' && Number.isInteger(body.ageMin)) out.ageMin = body.ageMin;
  if (body.ageMax === null) out.noAgeLimit = true;
  else if (typeof body.ageMax === 'number' && Number.isInteger(body.ageMax)) out.ageMax = body.ageMax;

  if (body.noExclusions === true) {
    out.noExclusions = true;
  } else {
    const excluded = list('excludedNeeds');
    if (excluded !== undefined) {
      if (!allIn(excluded, EXCLUDED_CODES)) return null;
      if (excluded.length > 0) out.excludedNeeds = excluded.join(',');
    }
  }
  if (typeof body.ownerRole === 'string') out.ownerRole = body.ownerRole;
  if (typeof body.ownerEmail === 'string') out.ownerEmail = body.ownerEmail;
  if (typeof body.reviewBy === 'string') out.reviewBy = body.reviewBy;
  const districts = list('districts');
  if (districts !== undefined) {
    const normal = districts.map((district) => normaliseDistrict(district));
    if (normal.some((district) => district === null)) return null;
    out.districts = normal.join(',');
  }
  return out;
}
