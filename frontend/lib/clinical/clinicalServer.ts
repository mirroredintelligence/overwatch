import type { Session } from '@/lib/auth/session';
import { fhirFetch } from '@/lib/fhir/client';
import { advisorContactFromJson, seenFromJson, type AdvisorContact, type Seen } from './seen';
import { clinicalRequestFromTask, type ClinicalRequest } from './task';

// Server-only: the clinical lists, one request, the clinician's presence and the count of advisors
// available, from the back end (R13, W7A). The caller's token is the only thing that says whose they
// are. The presence and the count are at the back end's root, not under /fhir.

type Auth = Pick<Session, 'backendToken'>;

/** The tabs of the queue and the Task status each one lists (DEC-774 item 4). */
export const TAB_STATUS = { waiting: 'requested', mine: 'in-progress', done: 'completed' } as const;
export type Tab = keyof typeof TAB_STATUS;
export const TABS = Object.keys(TAB_STATUS) as Tab[];

export async function readList(session: Auth, tab: Tab): Promise<ClinicalRequest[]> {
  const { data } = await fhirFetch<{ entry?: { resource?: unknown }[] }>(
    `/Task?code=clinical-advice&status=${TAB_STATUS[tab]}`,
    { token: session.backendToken },
  );
  return (data.entry ?? []).map((item) => clinicalRequestFromTask(item.resource));
}

export const readQueue = (session: Auth) => readList(session, 'waiting');

export async function readRequest(session: Auth, id: string): Promise<ClinicalRequest> {
  const { data } = await fhirFetch<unknown>(`/Task/${encodeURIComponent(id)}`, { token: session.backendToken });
  return clinicalRequestFromTask(data);
}

/**
 * What the advisor saw when they asked (W9G). Only the clinician who holds the request reads it: any other
 * caller is the back end's one 404. A display that cannot be read whole throws, so it is never half shown.
 */
export async function readSeen(session: Auth, id: string): Promise<Seen> {
  const { data } = await fhirFetch<unknown>(`/clinical/requests/${encodeURIComponent(id)}/seen`, { token: session.backendToken, root: true });
  return seenFromJson(data);
}

/**
 * The number to phone the advisor on (W9G): their work phone if the tenant holds one, else the tenant's
 * advisor line, else none. Personal data: it is returned to the caller and goes nowhere else (not logged,
 * not stored, not in a URL).
 */
export async function readAdvisorContact(session: Auth, id: string): Promise<AdvisorContact> {
  const { data } = await fhirFetch<unknown>(`/clinical/requests/${encodeURIComponent(id)}/advisor-contact`, { token: session.backendToken, root: true });
  return advisorContactFromJson(data);
}

export async function readAvailable(session: Auth): Promise<number> {
  const { data } = await fhirFetch<{ available?: unknown }>('/clinical/available', { token: session.backendToken, root: true });
  if (typeof data.available !== 'number') throw new Error('The back end sent no count of advisors.');
  return data.available;
}

export type Presence = 'available' | 'busy' | 'away';
export const PRESENCES: readonly Presence[] = ['available', 'busy', 'away'];

/** The clinician's own presence (null when none is set or it has lapsed) and the count of advisors. */
export async function readPresence(session: Auth): Promise<{ presence: Presence | null; available: number }> {
  const { data } = await fhirFetch<{ presence?: unknown; available?: unknown }>('/clinical/presence', { token: session.backendToken, root: true });
  if (typeof data.available !== 'number') throw new Error('The back end sent no count of advisors.');
  const presence = data.presence;
  if (presence !== null && !(typeof presence === 'string' && (PRESENCES as readonly string[]).includes(presence))) {
    throw new Error('The back end sent a presence that is not known.');
  }
  return { presence: presence as Presence | null, available: data.available };
}
