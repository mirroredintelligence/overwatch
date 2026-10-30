import { AGE_BANDS, labelOf, NEEDS, URGENCIES } from '@/lib/advisor/codes';
import { clinicalRequestFromTask, type ClinicalRequest, type Glance, type Urgency } from './task';

// A clinical request as the queue shows it (W44): the urgency, the reason and one line about the case.
// The back end's Task carries the case's glance (DEC-774), so the line is the advisor's own record:
// age band, needs, NEWS2 and the case urgency. It carries no postcode and no referrer.

export type { Urgency };
export type QueueItem = ClinicalRequest;

export const WHY_TEXT: Readonly<Record<string, string>> = {
  'borderline-criteria': 'Borderline criteria',
  'unsure-of-urgency': 'Unsure of urgency',
  other: 'Other',
};

export function urgencyText(urgency: Urgency): string {
  return urgency === 'now' ? 'Now' : 'Within 15 min';
}

export const queueItemFromTask = clinicalRequestFromTask;

/**
 * "80+ · Frailty, Fall · NEWS2 2 · Within 2 hrs": what the case holds, in that order, leaving out what
 * is not recorded. Null when the case could not be read (no glance).
 */
export function summaryLine(glance: Glance | null): string | null {
  if (glance === null) return null;
  const needs = glance.needs.map((code) => NEEDS.find((need) => need.code === code)?.short ?? code);
  return [
    labelOf(AGE_BANDS, glance.ageBand),
    needs.length > 0 ? needs.join(', ') : null,
    glance.news2 === null ? null : `NEWS2 ${glance.news2}`,
    labelOf(URGENCIES, glance.caseUrgency),
  ]
    .filter((part): part is string => part !== null && part !== '')
    .join(' · ');
}
