// The BFF's mapping between the screen's answers and the back end's step values (R10 $draft), and
// back to the screen's field names. The invitation's values (organisation name, ODS code, service
// name) are read from the back end and never taken from the browser.

import type { FieldIssue, StepName, StepValues } from './types';

export const STEP_FIELDS: Record<StepName, readonly string[]> = {
  organisation: ['orgType', 'contactName', 'contactRole', 'contact'],
  location: ['fixedSite', 'postcode', 'addressId', 'address', 'siteName', 'siteType', 'hours', 'siteOdsCode'],
  service: [],
  reporting: [],
  api: [],
};

const CONTACT_FIELDS = new Set(['contact', 'contactEmail', 'contactPhone']);

/** The text of a back-end refusal that only says a value is missing, by the page's field. */
const MISSING: Record<string, string> = {
  orgType: 'Choose the organisation type',
  contactName: 'Enter your name',
  contact: 'Enter an email address or phone number',
};

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : undefined;
}

export function organisationValues(
  body: Record<string, unknown>,
  locked: { organisationName: string; odsCode: string },
): Record<string, unknown> {
  const values: Record<string, unknown> = { name: locked.organisationName, odsCode: locked.odsCode };
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

/** The page's answers for a saved organisation step, from the back end's stored values. */
export function organisationAnswers(stored: StepValues): Record<string, string> {
  const answers: Record<string, string> = {};
  if (typeof stored.orgType === 'string') answers.orgType = stored.orgType;
  if (typeof stored.contactName === 'string') answers.contactName = stored.contactName;
  const contact = typeof stored.contactEmail === 'string' && stored.contactEmail !== ''
    ? stored.contactEmail
    : typeof stored.contactPhone === 'string' ? stored.contactPhone : undefined;
  if (contact !== undefined) answers.contact = contact;
  return answers;
}

/** The page's field a back-end field belongs to. Either contact field is the one contact box. */
export function locationValues(_body: Record<string, unknown>): Record<string, unknown> {
  throw new Error('not implemented');
}

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
