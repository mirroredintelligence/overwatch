import { codeSystemUrl } from '@/lib/fhir/codes';

// The executive's and the shift lead's alert preferences (W39, R12). The screens speak in the BFF's
// plain shape; the back end keeps them as one FHIR Subscription per practitioner, with one extension
// per setting. This module is pure: it maps between the two and refuses what the screens cannot offer.

export const ALERT_KINDS = ['service-closed', 'over-capacity', 'not-updated', 'system-pressure'] as const;
export type AlertKind = (typeof ALERT_KINDS)[number];

/** The not-updated windows the screens offer (domain/rules/alerts.py NOT_UPDATED_HOURS). */
export const NOT_UPDATED_CHOICES = [2, 4] as const;
/** The acknowledgement windows the screens offer (domain/rules/alerts.py ACK_MINUTES). */
export const ACK_CHOICES = [10, 15, 30] as const;
export const QUIET_START = '22:00';
export const QUIET_END = '06:00';

export type AlertPreferences = {
  kinds: AlertKind[];
  notUpdatedHours: 2 | 4;
  dailySummary: boolean;
  weeklySummary: boolean;
  quietHours: { start: string; end: string } | null;
  quietCriticalOnly: boolean;
  ackMinutes: 10 | 15 | 30;
  /** The deputy's practitioner reference. Empty until the executive names one. */
  deputy: string;
};

/** The rule book's defaults: every alert on except the weekly summary (W39). */
export const DEFAULT_ALERT_PREFERENCES: AlertPreferences = {
  kinds: [...ALERT_KINDS],
  notUpdatedHours: 2,
  dailySummary: true,
  weeklySummary: false,
  quietHours: null,
  quietCriticalOnly: true,
  ackMinutes: 15,
  deputy: '',
};

/** A refusal that names the field, never the value. */
export class AlertPreferencesError extends Error {
  readonly field: string;
  constructor(field: string) {
    super(`${field} is not valid`);
    this.name = 'AlertPreferencesError';
    this.field = field;
  }
}

const SETTING = (name: string) => codeSystemUrl(`alert-preferences/${name}`);
const PRACTITIONER = 'Practitioner/';
const REASON = 'Alert preferences of a shift lead or an executive';
const CRITERIA = 'alert-preferences';
const QUIET_TEXT = `${QUIET_START}-${QUIET_END}`;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The BFF's shape, checked. Throws AlertPreferencesError naming the first field that is wrong. */
export function parseAlertPreferences(input: unknown): AlertPreferences {
  if (!isRecord(input)) throw new AlertPreferencesError('body');
  const { kinds, notUpdatedHours, dailySummary, weeklySummary, quietHours, quietCriticalOnly, ackMinutes, deputy } = input;

  if (!Array.isArray(kinds) || !kinds.every((k) => (ALERT_KINDS as readonly unknown[]).includes(k))) {
    throw new AlertPreferencesError('kinds');
  }
  if (!(NOT_UPDATED_CHOICES as readonly unknown[]).includes(notUpdatedHours)) {
    throw new AlertPreferencesError('notUpdatedHours');
  }
  if (typeof dailySummary !== 'boolean') throw new AlertPreferencesError('dailySummary');
  if (typeof weeklySummary !== 'boolean') throw new AlertPreferencesError('weeklySummary');
  if (typeof quietCriticalOnly !== 'boolean') throw new AlertPreferencesError('quietCriticalOnly');
  if (!(ACK_CHOICES as readonly unknown[]).includes(ackMinutes)) throw new AlertPreferencesError('ackMinutes');
  if (quietHours !== null) {
    if (!isRecord(quietHours) || quietHours.start !== QUIET_START || quietHours.end !== QUIET_END) {
      throw new AlertPreferencesError('quietHours');
    }
  }
  if (typeof deputy !== 'string' || deputy.trim() === '') throw new AlertPreferencesError('deputy');

  return {
    kinds: [...new Set(kinds as AlertKind[])],
    notUpdatedHours: notUpdatedHours as 2 | 4,
    dailySummary,
    weeklySummary,
    quietHours: quietHours === null ? null : { start: QUIET_START, end: QUIET_END },
    quietCriticalOnly,
    ackMinutes: ackMinutes as 10 | 15 | 30,
    deputy: deputy.trim(),
  };
}

/** The Subscription the back end takes for these preferences (R12, subscription_mapping.py). */
export function subscriptionFromPreferences(prefs: AlertPreferences, practitionerId: string): Record<string, unknown> {
  const extension: Record<string, unknown>[] = prefs.kinds.map((kind) => ({ url: SETTING('kind'), valueCode: kind }));
  extension.push({ url: SETTING('not-updated-hours'), valueInteger: prefs.notUpdatedHours });
  extension.push({ url: SETTING('ack-minutes'), valueInteger: prefs.ackMinutes });
  extension.push({ url: SETTING('quiet-critical-only'), valueBoolean: prefs.quietCriticalOnly });
  if (prefs.quietHours !== null) extension.push({ url: SETTING('quiet-hours'), valueString: QUIET_TEXT });
  if (prefs.deputy !== '') extension.push({ url: SETTING('deputy'), valueReference: { reference: `${PRACTITIONER}${prefs.deputy}` } });
  extension.push({ url: SETTING('daily-summary'), valueBoolean: prefs.dailySummary });
  extension.push({ url: SETTING('weekly-summary'), valueBoolean: prefs.weeklySummary });
  return {
    resourceType: 'Subscription',
    id: practitionerId,
    status: prefs.kinds.length > 0 ? 'active' : 'off',
    reason: REASON,
    criteria: CRITERIA,
    channel: { type: 'message' },
    extension,
  };
}

/** The preferences a Subscription holds, read back for the screens. Missing settings take the defaults. */
export function preferencesFromSubscription(subscription: unknown): AlertPreferences {
  if (!isRecord(subscription)) throw new AlertPreferencesError('Subscription');
  const items = Array.isArray(subscription.extension) ? (subscription.extension as Record<string, unknown>[]) : [];
  const one = (name: string) => items.find((item) => item.url === SETTING(name));
  const kinds = items
    .filter((item) => item.url === SETTING('kind'))
    .map((item) => item.valueCode)
    .filter((k): k is AlertKind => (ALERT_KINDS as readonly unknown[]).includes(k));
  const reference = one('deputy')?.valueReference;
  const deputyRef = isRecord(reference) && typeof reference.reference === 'string' ? reference.reference : '';
  return {
    kinds,
    notUpdatedHours: (one('not-updated-hours')?.valueInteger ?? DEFAULT_ALERT_PREFERENCES.notUpdatedHours) as 2 | 4,
    dailySummary: (one('daily-summary')?.valueBoolean ?? DEFAULT_ALERT_PREFERENCES.dailySummary) as boolean,
    weeklySummary: (one('weekly-summary')?.valueBoolean ?? DEFAULT_ALERT_PREFERENCES.weeklySummary) as boolean,
    quietHours: one('quiet-hours') ? { start: QUIET_START, end: QUIET_END } : null,
    quietCriticalOnly: (one('quiet-critical-only')?.valueBoolean ?? DEFAULT_ALERT_PREFERENCES.quietCriticalOnly) as boolean,
    ackMinutes: (one('ack-minutes')?.valueInteger ?? DEFAULT_ALERT_PREFERENCES.ackMinutes) as 10 | 15 | 30,
    deputy: deputyRef.startsWith(PRACTITIONER) ? deputyRef.slice(PRACTITIONER.length) : '',
  };
}
