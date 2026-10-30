// Stub (W39 red): replaced by the implementation commit.
export const ALERT_KINDS = [] as const;
export type AlertKind = (typeof ALERT_KINDS)[number];
export type AlertPreferences = {
  kinds: AlertKind[];
  notUpdatedHours: 2 | 4;
  dailySummary: boolean;
  weeklySummary: boolean;
  quietHours: { start: string; end: string } | null;
  quietCriticalOnly: boolean;
  ackMinutes: 10 | 15 | 30;
  deputy: string;
};
export const DEFAULT_ALERT_PREFERENCES: AlertPreferences = {
  kinds: [], notUpdatedHours: 2, dailySummary: false, weeklySummary: false,
  quietHours: null, quietCriticalOnly: true, ackMinutes: 15, deputy: '',
};
export class AlertPreferencesError extends Error {}
export function parseAlertPreferences(input: unknown): AlertPreferences {
  void input;
  throw new AlertPreferencesError('not implemented');
}
export function subscriptionFromPreferences(prefs: AlertPreferences, practitionerId: string): Record<string, unknown> {
  void prefs; void practitionerId;
  throw new Error('not implemented');
}
export function preferencesFromSubscription(subscription: unknown): AlertPreferences {
  void subscription;
  throw new Error('not implemented');
}
