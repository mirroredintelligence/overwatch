// The reporting step and the API answer (W26). Pure: the browser and the BFF both use it. The count
// the applicant picks is sent as the back end's measure code (DEC-688); the back end's own list is
// checked before a value is passed on.

import type { FieldIssue } from './types';

export type ReportingAnswers = {
  /** The measure's code, as the back end takes it (`free-beds` for both bed chips). */
  counts?: string;
  usualLow?: string;
  usualHigh?: string;
  cadence?: string;
  channel?: string;
  holderName?: string;
  contactMobile?: string;
  contactEmail?: string;
};

export type ApiAnswers = { wanted?: boolean; name?: string; address?: string; connection?: string; dataType?: string };

/** The measures the back end holds, as the screen offers them. "Other" is not one (H-359). */
const MEASURES = ['referrals-acceptable', 'free-beds', 'free-slots', 'packages-free'] as const;
const CADENCES = ['every-2-hrs', 'twice-a-day', 'once-a-day'] as const;
const CHANNELS = ['text', 'email', 'push'] as const;
const MOBILE = /^07\d{9}$/;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const MAX_USUAL = 999;

/** The screen's count chips and the back end's measure each one sends. Both bed chips send `free-beds`. */
const COUNT_CODES: Readonly<Record<string, string>> = {
  referrals: 'referrals-acceptable',
  beds: 'free-beds',
  'virtual-beds': 'free-beds',
  slots: 'free-slots',
  packages: 'packages-free',
};

/** The back end's measure code for a count the screen offers, or null for "Other" or anything else. */
export function measureCodeOf(counts: string): string | null {
  return COUNT_CODES[counts] ?? null;
}

function whole(text: string | undefined): number | null {
  if (text === undefined || !/^\d{1,3}$/.test(text.trim())) return null;
  const value = Number(text.trim());
  return value <= MAX_USUAL ? value : null;
}

function mobile(text: string | undefined): boolean {
  return text !== undefined && MOBILE.test(text.replace(/[\s-]/g, ''));
}

export function validateReporting(answers: ReportingAnswers): FieldIssue[] {
  const issues: FieldIssue[] = [];
  if (answers.counts === undefined || measureCodeOf(answers.counts) === null) {
    issues.push({ field: 'counts', message: 'Choose what you count' });
  }
  const low = whole(answers.usualLow);
  const high = whole(answers.usualHigh);
  if (low === null) issues.push({ field: 'usualLow', message: 'Enter the lowest usual number' });
  if (high === null) issues.push({ field: 'usualHigh', message: 'Enter the highest usual number' });
  else if (low !== null && high < low) issues.push({ field: 'usualHigh', message: 'Highest usual number must be at least the lowest' });
  if (answers.cadence === undefined || !(CADENCES as readonly string[]).includes(answers.cadence)) {
    issues.push({ field: 'cadence', message: 'Choose how often you report' });
  }
  if (answers.channel === undefined || !(CHANNELS as readonly string[]).includes(answers.channel)) {
    issues.push({ field: 'channel', message: 'Choose how you will report' });
  }
  if (answers.holderName === undefined || answers.holderName.trim() === '') {
    issues.push({ field: 'holderName', message: 'Enter who holds this phone' });
  }
  if (answers.channel === 'text' || answers.channel === 'push') {
    if (!mobile(answers.contactMobile)) {
      issues.push({ field: 'contactMobile', message: 'Enter a UK mobile number, like 07700 900456' });
    }
  }
  if (answers.channel === 'email' && !EMAIL.test((answers.contactEmail ?? '').trim())) {
    issues.push({ field: 'contactEmail', message: 'Enter an email address' });
  }
  return issues;
}

export function validateApi(answers: ApiAnswers): FieldIssue[] {
  if (answers.wanted !== true) return [];
  const issues: FieldIssue[] = [];
  if (answers.name === undefined || answers.name.trim() === '') issues.push({ field: 'name', message: 'Enter the API name' });
  if (!(answers.address ?? '').startsWith('https://') || (answers.address ?? '').length <= 'https://'.length) {
    issues.push({ field: 'address', message: 'Enter the API address, starting https://' });
  }
  if (answers.connection === undefined || answers.connection.trim() === '') {
    issues.push({ field: 'connection', message: 'Choose a connection type' });
  }
  if (answers.dataType === undefined || answers.dataType.trim() === '') issues.push({ field: 'dataType', message: 'Choose a data type' });
  return issues;
}

/** The reporting step's values (R10 ReportingStep), or null when the measure or the cadence is not one the back end holds. */
export function reportingValues(body: Record<string, unknown>): Record<string, unknown> | null {
  const measure = body.measure;
  if (typeof measure !== 'string' || !(MEASURES as readonly string[]).includes(measure)) return null;
  const cadence = body.cadence;
  if (typeof cadence !== 'string' || !(CADENCES as readonly string[]).includes(cadence)) return null;
  const channel = body.channel;
  if (typeof channel !== 'string' || !(CHANNELS as readonly string[]).includes(channel)) return null;

  const values: Record<string, unknown> = { measure, cadence, channel };
  const range = body.usualRange;
  if (Array.isArray(range) && range.length === 2 && range.every((n) => Number.isInteger(n) && n >= 0 && n <= MAX_USUAL)) {
    values.usualLow = range[0];
    values.usualHigh = range[1];
  }
  if (typeof body.holderName === 'string') values.holderName = body.holderName.trim();
  if (channel === 'email') {
    if (typeof body.contactEmail === 'string') values.contactEmail = body.contactEmail.trim();
  } else if (typeof body.contactMobile === 'string') {
    values.contactMobile = body.contactMobile.replace(/[\s-]/g, '');
  }
  return values;
}

/** The API answer's values (R10 ApiStep). "Wanted" alone when there is no API. */
export function apiValues(body: Record<string, unknown>): Record<string, unknown> {
  if (body.wanted !== true) return { wanted: false };
  const values: Record<string, unknown> = { wanted: true };
  if (typeof body.name === 'string') values.name = body.name.trim();
  if (typeof body.address === 'string') values.address = body.address.trim();
  if (typeof body.connection === 'string') values.connection = body.connection.trim();
  if (typeof body.dataType === 'string') values.dataType = body.dataType.trim();
  return values;
}
