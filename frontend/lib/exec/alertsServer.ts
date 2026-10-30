import type { Session } from '@/lib/auth/session';
import { readBoard } from '@/lib/board/read';
import type { Board } from '@/lib/board/types';
import { fhirFetch } from '@/lib/fhir/client';
import { alertItemFromTask, type AlertItem } from './alerts';

// Server-only: the caller's alerts from the back end (R12, GET /fhir/Task with the alert code and
// owner=me; the acknowledged and closed lists add a status, W7A) and the board's names for their services. A board that cannot be read leaves the names out;
// it does not hide the alerts.

export const ALERT_ROLES = ['exec', 'lead'] as const;

/** The lists an executive can ask for: the open alerts, and the acknowledged and closed ones (W7A, DEC-775). */
export const ALERT_STATES = ['open', 'acknowledged', 'closed'] as const;
export type AlertState = (typeof ALERT_STATES)[number];

export const openAlerts = (session: Pick<Session, 'backendToken'>) => alertsByState(session, 'open');

export async function alertsByState(session: Pick<Session, 'backendToken'>, state: AlertState): Promise<AlertItem[]> {
  const status = state === 'open' ? '' : `&status=${state}`;
  const { data } = await fhirFetch<{ entry?: { resource?: unknown }[] }>(`/Task?code=acknowledge-alert&owner=me${status}`, {
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
