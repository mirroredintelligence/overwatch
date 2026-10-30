// Stub (W40 red).
import type { BoardEntry } from '@/lib/board/types';
export type AlertItem = {
  id: string;
  kind: 'service-closed' | 'over-capacity' | 'not-updated' | 'system-pressure';
  serviceId: string | null;
  serviceName: string | null;
  detail: string | null;
  raisedAt: string;
  state: 'new' | 'escalated';
  escalatesAt: string | null;
  escalatesTo: 'deputy' | null;
};
export function alertItemFromTask(task: unknown, entryFor: (serviceId: string) => BoardEntry | undefined): AlertItem {
  void task; void entryFor;
  throw new Error('not implemented');
}
export function alertTitle(item: AlertItem): string {
  void item;
  throw new Error('not implemented');
}
