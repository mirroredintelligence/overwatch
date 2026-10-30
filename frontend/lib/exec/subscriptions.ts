import { randomUUID } from 'node:crypto';
import type { Session } from '@/lib/auth/session';
import { fhirFetch } from '@/lib/fhir/client';
import {
  preferencesFromSubscription,
  subscriptionFromPreferences,
  type AlertPreferences,
} from './alertPrefs';

// Server-only. The caller's own alert preferences from the back end (R12, `GET` and `PUT
// /fhir/Subscription`). The practitioner is the token's subject; the back end never takes one from
// the browser. A save reads the current version first, because the back end refuses a PUT with no
// If-Match (428) and a stale one (412). That read and write are not one lock: see the known issues.

export type StoredPreferences = { practitionerId: string; version: string; preferences: AlertPreferences };

type Bundle = { entry?: { resource?: Record<string, unknown> }[] };

function subscriptionOf(bundle: Bundle): Record<string, unknown> {
  const resource = bundle.entry?.[0]?.resource;
  if (!resource || typeof resource !== 'object') throw new Error('The back end sent no subscription.');
  return resource;
}

export async function readAlertPreferences(session: Pick<Session, 'backendToken'>): Promise<StoredPreferences> {
  const { data } = await fhirFetch<Bundle>('/Subscription', { token: session.backendToken });
  const subscription = subscriptionOf(data);
  const meta = (subscription.meta ?? {}) as { versionId?: unknown };
  return {
    practitionerId: String(subscription.id),
    version: typeof meta.versionId === 'string' ? meta.versionId : '1',
    preferences: preferencesFromSubscription(subscription),
  };
}

/** The saved preferences, as the back end answers the save. */
export async function saveAlertPreferences(session: Pick<Session, 'backendToken'>, prefs: AlertPreferences): Promise<AlertPreferences> {
  const current = await readAlertPreferences(session);
  const { data } = await fhirFetch<Record<string, unknown>>(`/Subscription/${encodeURIComponent(current.practitionerId)}`, {
    method: 'PUT',
    token: session.backendToken,
    body: subscriptionFromPreferences(prefs, current.practitionerId),
    ifMatch: `W/"${current.version}"`,
    idempotencyKey: randomUUID(),
  });
  return preferencesFromSubscription(data);
}
