import type { Session } from '@/lib/auth/session';
import { fhirFetch } from '@/lib/fhir/client';
import { queueItemFromTask, type QueueItem } from './queue';

// Server-only: the clinical queue and the count of advisors available, from the back end (R13). The
// caller's token is the only thing that says whose queue it is.

const QUEUE_PATH = '/Task?code=clinical-advice&status=requested';

export async function readQueue(session: Pick<Session, 'backendToken'>): Promise<QueueItem[]> {
  const { data } = await fhirFetch<{ entry?: { resource?: unknown }[] }>(QUEUE_PATH, { token: session.backendToken });
  return (data.entry ?? []).map((item) => queueItemFromTask(item.resource));
}

export async function readAvailable(session: Pick<Session, 'backendToken'>): Promise<number> {
  const { data } = await fhirFetch<{ available?: unknown }>('/clinical/available', { token: session.backendToken });
  if (typeof data.available !== 'number') throw new Error('The back end sent no count of advisors.');
  return data.available;
}
