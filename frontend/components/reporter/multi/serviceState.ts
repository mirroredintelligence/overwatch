// The state line of one service on a phone with several (W38). Every text here is the one the
// screens show, so a test and a reporter read the same words.

export type ServiceState = 'confirmed' | 'due' | 'paused';

export type ServiceRow = {
  id: string;
  name: string;
  letter?: string;
  state: ServiceState;
  recordedValue: number | null;
  unitLabel: string;
  at: string | null;
  nextDue: string | null;
  replyBy?: string;
  pausedUntil?: string;
  pendingAcceptance: boolean;
};

export function stateText(row: ServiceRow): string {
  if (row.state === 'confirmed') return `Confirmed ${row.at ?? ''} · Next due ${row.nextDue ?? ''}`;
  if (row.state === 'paused') return `Paused · Until ${row.pausedUntil ?? ''}`;
  return `Due now · By ${row.replyBy ?? ''}`;
}
