import { describe, expect, it } from 'vitest';
import {
  ALERT_KINDS,
  AlertPreferencesError,
  DEFAULT_ALERT_PREFERENCES,
  parseAlertPreferences,
  preferencesFromSubscription,
  subscriptionFromPreferences,
  type AlertPreferences,
} from './alertPrefs';

const VALID: AlertPreferences = {
  kinds: ['service-closed', 'over-capacity', 'not-updated', 'system-pressure'],
  notUpdatedHours: 2,
  dailySummary: true,
  weeklySummary: false,
  quietHours: { start: '22:00', end: '06:00' },
  quietCriticalOnly: true,
  ackMinutes: 15,
  deputy: 'pr-0042',
};

describe('alert preference defaults (the rule book, W39)', () => {
  it('turns every alert on except the weekly summary, with a 15 minute acknowledgement', () => {
    expect([...DEFAULT_ALERT_PREFERENCES.kinds].sort()).toEqual([...ALERT_KINDS].sort());
    expect(DEFAULT_ALERT_PREFERENCES.weeklySummary).toBe(false);
    expect(DEFAULT_ALERT_PREFERENCES.dailySummary).toBe(true);
    expect(DEFAULT_ALERT_PREFERENCES.notUpdatedHours).toBe(2);
    expect(DEFAULT_ALERT_PREFERENCES.ackMinutes).toBe(15);
    expect(DEFAULT_ALERT_PREFERENCES.quietHours).toBeNull();
  });
});

describe('parseAlertPreferences (the route refuses what the screens cannot offer)', () => {
  it('accepts a complete set of preferences', () => {
    expect(parseAlertPreferences(VALID)).toEqual(VALID);
  });

  it('refuses an acknowledgement window that is not 10, 15 or 30 minutes', () => {
    expect(() => parseAlertPreferences({ ...VALID, ackMinutes: 20 })).toThrow(AlertPreferencesError);
  });

  it('refuses a not-updated window that is not 2 or 4 hours', () => {
    expect(() => parseAlertPreferences({ ...VALID, notUpdatedHours: 3 })).toThrow(AlertPreferencesError);
  });

  it('refuses an empty deputy', () => {
    expect(() => parseAlertPreferences({ ...VALID, deputy: '' })).toThrow(AlertPreferencesError);
  });

  it('refuses quiet hours other than 22:00 to 06:00, and an unknown alert kind', () => {
    expect(() => parseAlertPreferences({ ...VALID, quietHours: { start: '21:00', end: '06:00' } })).toThrow(AlertPreferencesError);
    expect(() => parseAlertPreferences({ ...VALID, kinds: ['everything'] })).toThrow(AlertPreferencesError);
  });

  it('refuses a body that is not an object', () => {
    expect(() => parseAlertPreferences('ackMinutes=15')).toThrow(AlertPreferencesError);
  });
});

describe('the FHIR Subscription mapping (R12)', () => {
  it('writes a Subscription with the alert criteria, a message channel and one extension per setting', () => {
    const sub = subscriptionFromPreferences(VALID, 'pr-0042');
    expect(sub.resourceType).toBe('Subscription');
    expect(sub.id).toBe('pr-0042');
    expect(sub.criteria).toBe('alert-preferences');
    expect(sub.channel).toEqual({ type: 'message' });
    expect(sub.status).toBe('active');
    const extensions = sub.extension as { url: string }[];
    expect(extensions.every((e) => e.url.startsWith('https://diucs.example/CodeSystem/alert-preferences/'))).toBe(true);
  });

  it('gives the deputy as a Practitioner reference, and leaves out quiet hours when none are set', () => {
    const sub = subscriptionFromPreferences({ ...VALID, quietHours: null }, 'pr-0042');
    const extensions = sub.extension as { url: string; valueReference?: unknown; valueString?: string }[];
    expect(extensions.find((e) => e.url.endsWith('/deputy'))?.valueReference).toEqual({ reference: 'Practitioner/pr-0042' });
    expect(extensions.some((e) => e.url.endsWith('/quiet-hours'))).toBe(false);
  });

  it('reads back what it wrote', () => {
    const sub = subscriptionFromPreferences(VALID, 'pr-0042');
    expect(preferencesFromSubscription(sub)).toEqual(VALID);
  });
});
