// The registration steps' checks in the browser, in screen order and in the screen's words. The
// back end checks the same answers again on every save (R10 validate_step); a refusal from it is
// shown with the same field names, so the two never disagree about where a problem is.

import { ORGANISATION_TYPES } from './options';
import type { FieldIssue } from './types';

export type OrganisationAnswers = {
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
