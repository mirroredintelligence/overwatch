import type { Session } from '@/lib/auth/session';
import { fhirFetch } from '@/lib/fhir/client';
import { summaryFromParameters, weekStartFor, type WeekSummary } from './weekSummary';

// Server-only: one week's figures from the back end (R12, `GET /HealthcareService/$week-summary`). The
// caller's token is the only thing that says whose week this is.

export async function readWeekSummary(session: Pick<Session, 'backendToken'>, ending: string): Promise<WeekSummary> {
  const start = weekStartFor(ending);
  const { data } = await fhirFetch<unknown>(`/HealthcareService/$week-summary?weekStart=${start}`, { token: session.backendToken });
  return summaryFromParameters(data, null);
}
