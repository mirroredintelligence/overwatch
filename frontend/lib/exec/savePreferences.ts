import { bffRequest, type BffResult } from '@/lib/bff/browser';
import type { AlertPreferences } from './alertPrefs';

export const PREFERENCES_PATH = '/api/bff/exec/alert-preferences';
export const DEPUTY_REQUIRED = 'Enter who to alert next';
export const SAVE_FAILED = 'Could not save your choices. Try again.';

/** Sends the whole preference state (the back end takes all of it, W39). A missing deputy is refused here, before the call. */
export function savePreferences(prefs: AlertPreferences): Promise<BffResult<AlertPreferences>> {
  return bffRequest<AlertPreferences>(PREFERENCES_PATH, { method: 'PUT', body: prefs });
}

export function hasDeputy(prefs: Pick<AlertPreferences, 'deputy'>): boolean {
  return prefs.deputy.trim() !== '';
}
