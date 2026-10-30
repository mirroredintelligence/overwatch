// The BFF's mapping between the screen's answers and the back end's step values (R10 $draft), and
// back to the screen's field names. The invitation's values (organisation name, ODS code, service
// name) are read from the back end and never taken from the browser.

import { normalisePostcode } from './postcode';
import type { FieldIssue, StepName, StepValues } from './types';

const DAY_CODES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;

export const STEP_FIELDS: Record<StepName, readonly string[]> = {
  // The organisation's name and ODS code are typed by the applicant (DEC-910); the reviewer's automatic
  // checks confirm them. The contact role is taken from the screen and never sent (DEC-906).
  organisation: ['name', 'odsCode', 'orgType', 'contactName', 'contactRole', 'contact'],
  location: ['fixedSite', 'postcode', 'addressId', 'address', 'siteName', 'siteType', 'hours', 'siteOdsCode'],
  service: [
    'category',
    'referralMethods',
    'spoaPhone',
    'acceptingDays',
    'acceptingStart',
    'acceptingEnd',
    'needs',
    'ageMin',
    'ageMax',
    'excludedNeeds',
    'noExclusions',
    'ownerRole',
    'ownerEmail',
    'reviewBy',
    'districts',
  ],
  reporting: ['measure', 'usualRange', 'cadence', 'channel', 'holderName', 'contactMobile', 'contactEmail'],
  api: ['wanted', 'name', 'address', 'connection', 'dataType'],
};

const CONTACT_FIELDS = new Set(['contact', 'contactEmail', 'contactPhone']);

/** The text of a back-end refusal that only says a value is missing, by the page's field. */
const MISSING: Record<string, string> = {
  name: 'Enter the organisation name',
  odsCode: 'Enter the ODS code',
  orgType: 'Choose the organisation type',
  contactName: 'Enter your name',
  contact: 'Enter an email address or phone number',
};

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : undefined;
}

export function organisationValues(body: Record<string, unknown>): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  const name = text(body.name);
  if (name !== undefined) values.name = name;
  const odsCode = text(body.odsCode);
  if (odsCode !== undefined) values.odsCode = odsCode;
  const orgType = text(body.orgType);
  if (orgType !== undefined) values.orgType = orgType;
  const contactName = text(body.contactName);
  if (contactName !== undefined) values.contactName = contactName;
  const contact = text(body.contact);
  if (contact !== undefined) {
    if (contact.includes('@')) values.contactEmail = contact;
    else values.contactPhone = contact;
  }
  return values;
}

/**
 * The page's answers for a saved organisation step, from the back end's stored values. A stored phone
 * number is never sent back to the page: the page is told its last three digits only (DEC-904).
 */
export function organisationAnswers(stored: StepValues): Record<string, string> {
  const answers: Record<string, string> = {};
  for (const key of ['name', 'odsCode', 'orgType', 'contactName', 'contactEmail'] as const) {
    const value = stored[key];
    if (typeof value === 'string' && value !== '') answers[key] = value;
  }
  if (typeof stored.contactPhoneEnding === 'string') answers.contactPhoneEnding = stored.contactPhoneEnding;
  return answers;
}

/**
 * The location step's values as the back end takes them (R10 LocationStep). Hours are text: the day
 * numbers become `mon,tue,…` (0 is Monday). A 24-hour service is `open24h` (see H-355: the back end
 * does not read that name yet, so the save is refused until it does).
 */
export function locationValues(body: Record<string, unknown>): Record<string, unknown> {
  const values: Record<string, unknown> = { fixedSite: body.fixedSite === true };
  if (body.fixedSite !== true) return values;

  const postcode = typeof body.postcode === 'string' ? normalisePostcode(body.postcode) : null;
  if (postcode !== null) values.postcode = postcode;
  const address = text(body.address);
  if (address !== undefined) values.address = address;
  const siteName = text(body.siteName);
  if (siteName !== undefined) values.siteName = siteName;
  const siteType = text(body.siteType);
  if (siteType !== undefined) values.siteType = siteType;

  const hours = typeof body.hours === 'object' && body.hours !== null ? (body.hours as Record<string, unknown>) : {};
  if (hours.allDay === true) {
    values.open24h = true;
  } else {
    const days = Array.isArray(hours.days) ? hours.days.filter((day): day is number => Number.isInteger(day) && day >= 0 && day <= 6) : [];
    if (days.length > 0) values.openingDays = [...new Set(days)].sort((a, b) => a - b).map((day) => DAY_CODES[day]).join(',');
    const opens = text(hours.opens);
    if (opens !== undefined) values.openingStart = opens;
    const closes = text(hours.closes);
    if (closes !== undefined) values.openingEnd = closes;
  }
  return values;
}

/** The page's field a back-end field belongs to. Either contact field is the one contact box. */
export function pageFieldFor(backendField: string): string {
  return CONTACT_FIELDS.has(backendField) ? 'contact' : backendField;
}

/** The field errors of a back-end refusal (an OperationOutcome): one per issue that names a field. */
export function issuesFromOutcome(outcome: unknown): FieldIssue[] {
  if (typeof outcome !== 'object' || outcome === null) return [];
  const issues = (outcome as { issue?: unknown }).issue;
  if (!Array.isArray(issues)) return [];
  const found: FieldIssue[] = [];
  for (const issue of issues) {
    const item = issue as { diagnostics?: unknown; expression?: unknown };
    const field = Array.isArray(item.expression) && typeof item.expression[0] === 'string' ? item.expression[0] : undefined;
    if (field === undefined || field === '') continue;
    const page = pageFieldFor(field);
    const said = typeof item.diagnostics === 'string' ? item.diagnostics : '';
    if (said === '') continue;
    found.push({ field: page, message: said === 'is required' && MISSING[page] !== undefined ? MISSING[page] : said });
  }
  return found;
}
