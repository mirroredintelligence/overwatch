import type { Role, Session } from '@/lib/auth/session';
import { fhirFetch, type FhirResult } from '@/lib/fhir/client';
import { NEEDS, PERIODS, type Need, type Period, type Planning } from './types';

// Server-only. The planning routes for the managers and the ICB (W51). Only the lead and the
// executive may read them, as the proxy's table says (proxy.ts, lib/auth/access.ts). The back end's
// planning route is the U43 use case behind a root path; the browser names only a period and a need.

export const PLANNING_ROLES: readonly Role[] = ['lead', 'exec'];

export function isPeriod(value: string | null): value is Period {
  return PERIODS.some((item) => item.value === value);
}

export function isNeed(value: string | null): value is Need {
  return NEEDS.some((item) => item.value === value);
}

export function planningCall(
  session: Pick<Session, 'backendToken'>,
  period: Period,
  need: Need,
): Promise<FhirResult<Planning>> {
  const query = new URLSearchParams({ period, need }).toString();
  return fhirFetch<Planning>(`/planning?${query}`, { root: true, token: session.backendToken });
}
