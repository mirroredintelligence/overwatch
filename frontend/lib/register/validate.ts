// The registration steps' checks in the browser, in screen order and in the screen's words. The
// back end checks the same answers again on every save (R10 validate_step); a refusal from it is
// shown with the same field names, so the two never disagree about where a problem is.

import { normalisePostcode } from './postcode';
import { ORGANISATION_TYPES } from './options';
import type { FieldIssue } from './types';

export type OrganisationAnswers = {
  /** The organisation's name and ODS code, typed by the applicant (DEC-910). */
  name?: string;
  odsCode?: string;
  orgType?: string;
  /** Shown on screen; the back end does not take it yet (W54 fragment). */
  partOf?: string;
  contactName?: string;
  contactRole?: string;
  contact?: string;
};

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const UK_PHONE = /^0\d{10}$/;

function blank(value: string | undefined): boolean {
  return value === undefined || value.trim() === '';
}

/** An email address or a full UK phone number (spaces and hyphens do not count, +44 is the same as 0). */
export function isEmailOrUkPhone(text: string): boolean {
  const trimmed = text.trim();
  if (EMAIL.test(trimmed)) return true;
  let compact = trimmed.replace(/[\s-]/g, '');
  if (compact.startsWith('+44')) compact = `0${compact.slice(3)}`;
  return UK_PHONE.test(compact);
}

export function validateOrganisation(answers: OrganisationAnswers): FieldIssue[] {
  const issues: FieldIssue[] = [];
  if (blank(answers.name)) issues.push({ field: 'name', message: 'Enter the organisation name' });
  if (blank(answers.odsCode)) issues.push({ field: 'odsCode', message: 'Enter the ODS code' });
  if (answers.orgType === undefined || !ORGANISATION_TYPES.some((option) => option.value === answers.orgType)) {
    issues.push({ field: 'orgType', message: 'Choose the organisation type' });
  }
  if (blank(answers.contactName)) issues.push({ field: 'contactName', message: 'Enter your name' });
  if (blank(answers.contactRole)) issues.push({ field: 'contactRole', message: 'Enter your role' });
  if (blank(answers.contact) || !isEmailOrUkPhone(answers.contact ?? '')) {
    issues.push({ field: 'contact', message: 'Enter an email address or phone number' });
  }
  return issues;
}

export type LocationAnswers = {
  fixedSite?: boolean;
  postcode?: string;
  /** The id of the address the lookup offered (screen state only). */
  addressId?: string;
  /** The label of the chosen address, which the back end stores (R10 LocationStep.address). */
  address?: string;
  siteName?: string;
  siteType?: string;
  days?: number[];
  allDay?: boolean;
  opens?: string;
  closes?: string;
  siteOdsCode?: string;
};

const SITE_TYPES: readonly string[] = ['ward', 'community-hospital', 'hub-or-base', 'clinic', 'other'];
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Minutes since midnight for a valid HH:MM, or null. */
function minutes(value: string | undefined): number | null {
  if (value === undefined || !TIME.test(value)) return null;
  const [hours, mins] = value.split(':').map(Number) as [number, number];
  return hours * 60 + mins;
}

/** The location step's checks, in screen order. A visiting service needs only its answer. */
export function validateLocation(answers: LocationAnswers): FieldIssue[] {
  if (answers.fixedSite === undefined) {
    return [{ field: 'fixedSite', message: 'Choose whether you have a fixed site' }];
  }
  if (answers.fixedSite === false) return [];

  const issues: FieldIssue[] = [];
  if (blank(answers.postcode)) {
    issues.push({ field: 'postcode', message: 'Enter a postcode' });
  } else if (normalisePostcode(answers.postcode ?? '') === null) {
    issues.push({ field: 'postcode', message: 'Enter a full postcode' });
  }
  if (blank(answers.address)) issues.push({ field: 'address', message: 'Choose the address' });
  if (blank(answers.siteName)) issues.push({ field: 'siteName', message: 'Enter the site name' });
  if (answers.siteType === undefined || !SITE_TYPES.includes(answers.siteType)) {
    issues.push({ field: 'siteType', message: 'Choose a site type' });
  }
  if (answers.allDay !== true) {
    if ((answers.days ?? []).length === 0) {
      issues.push({ field: 'opening', message: 'Choose the opening days, or 24 hours' });
    }
    const opens = minutes(answers.opens);
    const closes = minutes(answers.closes);
    if (opens === null) issues.push({ field: 'opens', message: 'Enter a time like 08:00' });
    if (closes === null) issues.push({ field: 'closes', message: 'Enter a time like 08:00' });
    if (opens !== null && closes !== null && closes <= opens) {
      issues.push({ field: 'closes', message: 'The closing time must be after the opening time' });
    }
  }
  return issues;
}
