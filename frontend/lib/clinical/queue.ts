// Stub (W44 red).
export type QueueItem = { id: string; urgency: 'now' | 'within-15-min'; why: string; requestedAt: string; status: string; caseId: string };
export function queueItemFromTask(task: unknown): QueueItem { void task; throw new Error('not implemented'); }
export function urgencyText(urgency: QueueItem['urgency']): string { void urgency; throw new Error('not implemented'); }
