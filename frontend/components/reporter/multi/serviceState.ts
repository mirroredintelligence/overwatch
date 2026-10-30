import { clock } from '@/lib/reporter/times';

// The state line of one service on a phone with several (W38, W8E). Every text here is the one the
// screens show, so a test and a reporter read the same words. The instants are the back end's, shown as
// the tenant's clock time (DEC-815: a row is due, confirmed or paused).

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
  pendingAcceptance: boolean;
};

export function stateText(row: ServiceRow): string {
  if (row.state === 'paused') return 'Paused';
  if (row.state === 'confirmed') {
    const at = clock(row.at);
    const next = clock(row.nextDue);
    return `Confirmed${at === '' ? '' : ` ${at}`}${next === '' ? '' : ` · Next due ${next}`}`;
  }
  const by = clock(row.replyBy);
  return `Due now${by === '' ? '' : ` · By ${by}`}`;
}

/** The services list the BFF gives, or null when it is not one (a failed read is not an empty list). */
export function readRows(body: unknown): ServiceRow[] | null {
  const list = (body as { services?: unknown } | undefined)?.services;
  if (!Array.isArray(list)) return null;
  const rows: ServiceRow[] = [];
  for (const item of list as Partial<ServiceRow>[]) {
    if (typeof item?.id !== 'string' || typeof item.name !== 'string' || typeof item.unitLabel !== 'string') return null;
    if (item.state !== 'confirmed' && item.state !== 'due' && item.state !== 'paused') return null;
    rows.push({
      id: item.id,
      name: item.name,
      state: item.state,
      recordedValue: typeof item.recordedValue === 'number' ? item.recordedValue : null,
      unitLabel: item.unitLabel,
      at: typeof item.at === 'string' ? item.at : null,
      nextDue: typeof item.nextDue === 'string' ? item.nextDue : null,
      pendingAcceptance: item.pendingAcceptance === true,
      ...(typeof item.letter === 'string' ? { letter: item.letter } : {}),
      ...(typeof item.replyBy === 'string' ? { replyBy: item.replyBy } : {}),
    });
  }
  return rows;
}
