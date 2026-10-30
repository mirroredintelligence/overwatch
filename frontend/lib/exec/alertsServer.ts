import type { Session } from '@/lib/auth/session';
import { readBoard } from '@/lib/board/read';
import type { Board } from '@/lib/board/types';
import { fhirFetch } from '@/lib/fhir/client';
import { alertItemFromTask, type AlertItem } from './alerts';

// Server-only: the caller's open alerts from the back end (R12, GET /fhir/Task with the alert code and
// owner=me) and the board's names for their services. A board that cannot be read leaves the names out;
// it does not hide the alerts.

export const ALERT_ROLES = ['exec', 'lead'] as const;

export async function openAlerts(session: Pick<Session, 'backendToken'>): Promise<AlertItem[]> {
  const { data } = await fhirFetch<{ entry?: { resource?: unknown }[] }>('/Task?code=acknowledge-alert&owner=me', {
    token: session.backendToken,
  });
  let board: Board | null = null;
  try {
    board = await readBoard(session);
  } catch {
    board = null;
  }
  return (data.entry ?? []).map((item) =>
    alertItemFromTask(item.resource, (serviceId) => board?.entries.find((entry) => entry.serviceId === serviceId)),
  );
}
