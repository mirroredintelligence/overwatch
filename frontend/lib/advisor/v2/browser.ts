import { bffFetch, type BffReply } from '@/lib/advisor/browser';
import type { AgeCode, NeedCode, UrgencyCode } from '@/lib/advisor/codes';
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
