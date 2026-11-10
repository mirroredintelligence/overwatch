import { bffFetch, newIdempotencyKey, type BffReply } from '@/lib/advisor/browser';
import type { AgeCode, NeedCode, UrgencyCode } from '@/lib/advisor/codes';
import { parseCheck, type FitCheck } from './check';
import { parseFind, type FindRead } from './find';
import { parseOverview, type Overview } from './overview';

// The browser's calls for Advisor v2 (DEC-1366). Browse only: nothing is stored. The postcode goes in the body of
// one POST and is not kept by this module.

export type FindInput = { postcode: string; ageBand: AgeCode; needs: NeedCode[]; urgency: UrgencyCode };

export async function findServices(input: FindInput): Promise<FindRead | null> {
  const reply: BffReply<unknown> = await bffFetch<unknown>('/api/bff/advisor-v2/find', { method: 'POST', body: input });
  return reply.ok ? parseFind(reply.body) : null;
}

export async function readOverview(): Promise<Overview | null> {
  const reply: BffReply<unknown> = await bffFetch<unknown>('/api/bff/advisor-v2/capacity');
  return reply.ok ? parseOverview(reply.body) : null;
}

/** One patient against one service (DEC-1377). Browse only: the criteria go in the body of one POST and are not kept. */
export async function checkService(serviceId: string, input: FindInput): Promise<FitCheck | null> {
  const reply: BffReply<unknown> = await bffFetch<unknown>(`/api/bff/advisor-v2/services/${encodeURIComponent(serviceId)}/check`, {
    method: 'POST',
    body: input,
  });
  return reply.ok ? parseCheck(reply.body) : null;
}

export type AskResult = { kind: 'queued' } | { kind: 'already' } | { kind: 'failed' };

/** Asks the service for its capacity figure now. One key for the press, so a double press asks once. */
export async function askService(serviceId: string): Promise<AskResult> {
  const reply: BffReply<unknown> = await bffFetch<unknown>(`/api/bff/advisor-v2/services/${encodeURIComponent(serviceId)}/ask`, {
    method: 'POST',
    idempotencyKey: newIdempotencyKey(),
  });
  if (reply.ok) return { kind: 'queued' };
  return reply.status === 409 ? { kind: 'already' } : { kind: 'failed' };
}
